import argparse

from .config import Settings
from .db import make_sessions
from .payments.service import cleanup_expired


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['cleanup'])
    parser.add_argument('--batch-size', type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 10000:
        parser.error('batch-size must be 1..10000')
    sessions = make_sessions(Settings().database_url)
    with sessions() as session:
        print(f'Cancelled expired mock orders: {cleanup_expired(session, batch_size=args.batch_size)}')


if __name__ == '__main__':
    main()
