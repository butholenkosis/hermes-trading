"""
Fill the trading tables with realistic volume so EXPLAIN ANALYZE output is meaningful.
A handful of rows always gives a Seq Scan, whatever indexes exist.

    python manage.py seed_trading_data                    # defaults below
    python manage.py seed_trading_data --users 20 --days 90
    python manage.py seed_trading_data --wipe             # delete earlier seeded users first

Creates seeded users (seed_user_NN@hermes.test, password: hermes123), each with
holdings, transactions, signals, a portfolio snapshot every 5 minutes and a
stock snapshot every hour per holding. Defaults produce roughly:
    portfolio_snapshot ~520k, stock_snapshot ~216k, trading_transaction ~12k, trading_signal ~16k
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from trading_app.models import (Holding, PortfolioSnapshot, Signal, StockSnapshot,
                                Transaction, User)

SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA', 'AVGO', 'AMD', 'NFLX',
           'COST', 'PEP', 'ADBE', 'CRWD', 'PLTR', 'SMCI', 'ENPH', 'FSLR', 'ICLN', 'TAN']
INDEXES = ['S&P 500', 'NASDAQ 100']
BATCH = 5000


def money(x):
    return Decimal(str(round(x, 2)))


class Command(BaseCommand):
    help = 'Seed users, holdings, transactions, signals and snapshots in bulk'

    def add_arguments(self, parser):
        parser.add_argument('--users', type=int, default=20)
        parser.add_argument('--days', type=int, default=90, help='How many days of snapshot history')
        parser.add_argument('--holdings', type=int, default=5, help='Holdings per user')
        parser.add_argument('--wipe', action='store_true', help='Delete previously seeded users first')

    def handle(self, *args, **o):
        random.seed(42)
        if o['wipe']:
            n, _ = User.objects.filter(email__endswith='@hermes.test').delete()
            self.stdout.write(f'Wiped {n} seeded objects')

        # Fill timestamp/date fields ourselves; auto_now_add would stamp everything "now".
        for model, field in [(Transaction, 'date'), (Holding, 'date_purchased'),
                             (PortfolioSnapshot, 'timestamp'), (StockSnapshot, 'timestamp'),
                             (Signal, 'created_at')]:
            model._meta.get_field(field).auto_now_add = False

        now = timezone.now().replace(second=0, microsecond=0)
        start = now - timedelta(days=o['days'])

        for i in range(1, o['users'] + 1):
            email = f'seed_user_{i:02d}@hermes.test'
            user, created = User.objects.get_or_create(
                email=email,
                defaults={'username': f'seed_user_{i:02d}', 'name': f'Seed User {i:02d}',
                          'balance': money(random.uniform(20_000, 150_000))})
            if created:
                user.set_password('hermes123')
                user.save()
            elif PortfolioSnapshot.objects.filter(user=user).exists():
                self.stdout.write(f'  {email}: already seeded, skipped')
                continue
            self._seed_user(user, start, now, o['holdings'])
            self.stdout.write(f'  {email}: done')

        if connection.vendor == 'postgresql':
            with connection.cursor() as cur:
                for t in ['trading_user', 'trading_transaction', 'trading_holding',
                          'portfolio_snapshot', 'stock_snapshot', 'trading_signal']:
                    cur.execute(f'ANALYZE {t};')

        self.stdout.write(self.style.SUCCESS(
            f'Rows now: portfolio_snapshot={PortfolioSnapshot.objects.count()}, '
            f'stock_snapshot={StockSnapshot.objects.count()}, '
            f'trading_transaction={Transaction.objects.count()}, '
            f'trading_signal={Signal.objects.count()}'))

    def _seed_user(self, user, start, now, n_holdings):
        cash = float(user.balance)
        symbols = random.sample(SYMBOLS, n_holdings)
        price = {s: random.uniform(20, 900) for s in symbols}
        qty = {s: random.randint(5, 200) for s in symbols}

        # Holdings (current state)
        Holding.objects.bulk_create([
            Holding(user=user, stock=s, quantity=qty[s], buying_price=money(price[s]),
                    current_price=money(price[s] * random.uniform(0.85, 1.25)),
                    date_purchased=start)
            for s in symbols])

        # Transactions: ~600 over the period
        txs, bal = [], cash
        for _ in range(600):
            kind = random.choices(['buy', 'sell', 'deposit', 'withdrawal', 'dividend', 'fee'],
                                  weights=[40, 30, 10, 5, 10, 5])[0]
            amt = random.uniform(50, 5000)
            credit = amt if kind in ('sell', 'deposit', 'dividend') else 0
            debit = amt if credit == 0 else 0
            bal = max(bal + credit - debit, 0)
            txs.append(Transaction(
                user=user, transaction_type=kind, debit=money(debit), credit=money(credit),
                description=f'{kind} {random.choice(symbols)}', balance_after=money(bal),
                date=start + timedelta(seconds=random.randint(0, int((now - start).total_seconds())))))
        Transaction.objects.bulk_create(txs, batch_size=BATCH)

        # Signals: ~800, most already read, a few unread
        sigs = []
        for _ in range(800):
            s = random.choice(SYMBOLS)
            created_at = start + timedelta(seconds=random.randint(0, int((now - start).total_seconds())))
            recent = (now - created_at) < timedelta(days=3)
            sigs.append(Signal(
                user=user, stock=s,
                signal_type=random.choice(['index_addition', 'index_removal', 'price_target', 'volume_spike']),
                action=random.choice(['buy', 'sell', 'hold', 'watch']),
                title=f'{s} signal', description='Seeded signal for query testing',
                index_name=random.choice(INDEXES), current_price=money(random.uniform(20, 900)),
                created_at=created_at,
                is_read=not (recent and random.random() < 0.6),
                is_active=random.random() < 0.9))
        Signal.objects.bulk_create(sigs, batch_size=BATCH)

        # Portfolio snapshot every 5 minutes; stock snapshot every hour per holding
        ps, ss, t, step = [], [], start, 0
        while t <= now:
            for s in symbols:
                price[s] *= 1 + random.gauss(0, 0.0015)
            hv = sum(qty[s] * price[s] for s in symbols)
            ps.append(PortfolioSnapshot(user=user, timestamp=t, total_value=money(cash + hv),
                                        cash_balance=money(cash), holdings_value=money(hv)))
            if step % 12 == 0:
                for s in symbols:
                    ss.append(StockSnapshot(user=user, stock=s, timestamp=t, quantity=qty[s],
                                            current_price=money(price[s]),
                                            current_value=money(qty[s] * price[s])))
            if len(ps) >= BATCH:
                PortfolioSnapshot.objects.bulk_create(ps); ps = []
            if len(ss) >= BATCH:
                StockSnapshot.objects.bulk_create(ss); ss = []
            t += timedelta(minutes=5)
            step += 1
        PortfolioSnapshot.objects.bulk_create(ps)
        StockSnapshot.objects.bulk_create(ss)
