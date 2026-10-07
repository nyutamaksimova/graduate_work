# Сервис промокодов и подписок онлайн-кинотеатра

[Ссылка на репозиторий](https://github.com/nyutamaksimova/graduate_work)

FastAPI + PostgreSQL

Реализованы покупка по тарифу,
фиксированная цена по коду, триал, процентная скидка, ограничения срока и числа
применений, применение администратором, причины отказов, генерация кодов и
освобождение промокода при неуспешной оплате.

**Оплата тестовая: сервис не списывает деньги.** Её результат задаёт администратор.
Подписка выдаётся только после успешного результата, либо сразу при нулевой цене.

## API

Публичный `GET /api/v1/plans` показывает активные тарифы. Пользовательские запросы
требуют `Authorization: Bearer <access JWT>`. JWT содержит `sub` (UUID), `role`,
`exp`, необязательный `is_superuser`. Refresh-токен не принимается.
Административные операции разрешены ADMIN/SUPER_ADMIN либо is_superuser=true.

| Метод и путь                                   | Назначение                                         |
|------------------------------------------------|----------------------------------------------------|
| POST /api/v1/promocodes/preview                | Проверка и итоговая цена; резерв не создаётся      |
| POST /api/v1/orders                            | Покупка с промокодом или без него                  |
| GET /api/v1/orders/{id}                        | Свой заказ; администратор видит любой              |
| GET /api/v1/subscriptions/me                   | Срок и активность доступа                          |
| POST /api/v1/admin/plans                       | Создание тарифа                                    |
| POST /api/v1/admin/promocodes                  | Создание промокода                                 |
| PATCH /api/v1/admin/promocodes/{id}            | Включение/отключение кода                          |
| POST /api/v1/admin/promocodes/generate         | Генерация партии                                   |
| POST /api/v1/admin/users/{id}/orders           | Применение от имени пользователя с причиной        |
| POST /api/v1/admin/payments/{order_id}/resolve | succeeded/failed для тестовой оплаты               |
| GET /api/v1/admin/promo-attempts               | Журнал; фильтры user_id, error_code, limit, offset |
| GET /internal/v1/users/{id}/entitlements       | Проверка доступа с X-Service-Token                 |
