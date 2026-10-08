"""Shared Redis budgets for every promo endpoint; no PostgreSQL queries here."""
import hashlib

from redis import Redis
from redis.exceptions import RedisError

from .errors import DomainError

# Each admission checks both budgets and consumes both atomically. Rejected
# requests neither consume another identity's budget nor refresh any TTL.
ADMIT = """
local blocked = math.max(redis.call('PTTL', KEYS[5]), redis.call('PTTL', KEYS[6]), 0)
local wait = 0
for i = 1, 2 do
    if tonumber(redis.call('GET', KEYS[i]) or '0') >= tonumber(ARGV[i]) then
        wait = math.max(wait, redis.call('PTTL', KEYS[i]), 1)
    end
end
if blocked > 0 then return {2, math.ceil(math.max(blocked, wait) / 1000)} end
if wait > 0 then return {1, math.ceil(wait / 1000)} end
for i = 1, 2 do
    if redis.call('INCR', KEYS[i]) == 1 then
        redis.call('EXPIRE', KEYS[i], ARGV[3])
    end
end
return {0, 0}
"""

FAILURE = """
for i = 3, 4 do
    local failures = redis.call('INCR', KEYS[i])
    if failures == 1 then redis.call('EXPIRE', KEYS[i], ARGV[2]) end
    if failures >= tonumber(ARGV[1]) then
        redis.call('SET', KEYS[i+2], '1', 'EX', ARGV[3], 'NX')
    end
end
return 1
"""


class PromoGuard:
    def __init__(self, client: Redis, settings, prefix='loyalty:promo'):
        self.client, self.settings, self.prefix = client, settings, prefix

    @classmethod
    def from_settings(cls, settings):
        return cls(Redis.from_url(settings.redis_url, socket_connect_timeout=1,
                                  socket_timeout=1, decode_responses=True), settings)

    def _keys(self, user_id, ip):
        user = hashlib.sha256(str(user_id).encode()).hexdigest()
        address = hashlib.sha256(ip.encode()).hexdigest()
        roots = [f'{self.prefix}:user:{user}', f'{self.prefix}:ip:{address}']
        return [root + suffix for suffix in (':requests', ':failures', ':block') for root in roots]

    def _eval(self, script, keys, *args):
        try:
            return self.client.eval(script, len(keys), *keys, *args)
        except RedisError:
            # A missing guard must not turn into unlimited PostgreSQL traffic.
            raise DomainError('PROMO_PROTECTION_UNAVAILABLE',
                              'Защита промокодов временно недоступна', 503, headers={'Retry-After': '1'})

    def admit(self, user_id, ip):
        settings = self.settings
        status, wait = self._eval(ADMIT, self._keys(user_id, ip),
                                  settings.promo_user_limit, settings.promo_ip_limit, settings.promo_window_seconds)
        if status:
            code = 'PROMO_TEMPORARILY_BLOCKED' if status == 2 else 'PROMO_RATE_LIMITED'
            message = 'Попытки временно заблокированы' if status == 2 else 'Слишком много попыток применения промокода'
            raise DomainError(code, message, 429, headers={'Retry-After': str(wait)})

    def record_failure(self, user_id, ip):
        settings = self.settings
        self._eval(FAILURE, self._keys(user_id, ip), settings.promo_failure_threshold,
                   settings.promo_failure_window_seconds, settings.promo_block_seconds)


def request_ip(request):
    # Forwarded headers are deliberately not parsed here. In a proxy deployment
    # the ASGI server must trust only the gateway; standalone disables them.
    return request.client.host if request.client else 'unknown'


def admit_promo(request, user_id):
    request.app.state.promo_guard.admit(user_id, request_ip(request))


def rejected_promo(request, user_id, error_code):
    if error_code.startswith('PROMO_') or error_code == 'TRIAL_ALREADY_USED':
        request.app.state.promo_guard.record_failure(user_id, request_ip(request))
