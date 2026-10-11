"""
Load daily OHLCV history into the price_bar table.

    python manage.py load_prices                 # ~110 default tickers, 5 years, from yfinance
    python manage.py load_prices --tickers AAPL MSFT --period 1y
    python manage.py load_prices --from-csv      # only the small CSVs in trading_app/data/prices/

Re-running is safe: existing (symbol, date) rows are skipped.
"""
from decimal import Decimal
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand
from django.db import connection

from trading_app.models import PriceBar

# Large, liquid names (NASDAQ-100 / S&P 500 heavyweights) plus the clean-energy universe.
DEFAULT_TICKERS = [
    'AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'GOOG', 'META', 'TSLA', 'AVGO', 'COST',
    'NFLX', 'AMD', 'ADBE', 'PEP', 'CSCO', 'TMUS', 'INTC', 'CMCSA', 'TXN', 'QCOM',
    'INTU', 'AMGN', 'HON', 'AMAT', 'BKNG', 'ISRG', 'SBUX', 'MDLZ', 'GILD', 'ADP',
    'VRTX', 'REGN', 'ADI', 'LRCX', 'PANW', 'MU', 'SNPS', 'CDNS', 'KLAC', 'MELI',
    'PYPL', 'ASML', 'MAR', 'ORLY', 'CTAS', 'ABNB', 'CRWD', 'FTNT', 'MRVL', 'NXPI',
    'WDAY', 'ROP', 'PCAR', 'MNST', 'CPRT', 'PAYX', 'ODFL', 'ROST', 'KDP', 'DXCM',
    'IDXX', 'FAST', 'EA', 'CTSH', 'VRSK', 'BIIB', 'EXC', 'XEL', 'CSX', 'DDOG',
    'TEAM', 'ZS', 'ANSS', 'ON', 'GEHC', 'BKR', 'TTD', 'CDW', 'MCHP', 'DLTR',
    'JPM', 'V', 'MA', 'UNH', 'JNJ', 'XOM', 'PG', 'HD', 'KO', 'WMT',
    'BAC', 'CVX', 'LLY', 'ABBV', 'MRK', 'DIS', 'ORCL', 'CRM', 'PLTR', 'SMCI',
    'ICLN', 'TAN', 'QCLN', 'ENPH', 'FSLR', 'SEDG', 'RUN', 'PLUG',
]

CSV_DIR = Path(__file__).resolve().parents[2] / 'data' / 'prices'


def _dec(x):
    return Decimal(str(round(float(x), 4)))


class Command(BaseCommand):
    help = 'Load daily OHLCV price history into price_bar'

    def add_arguments(self, parser):
        parser.add_argument('--tickers', nargs='+', help='Tickers to load (default: built-in list)')
        parser.add_argument('--period', default='5y', help='yfinance period, e.g. 1y, 5y, max')
        parser.add_argument('--from-csv', action='store_true', help='Load trading_app/data/prices/*.csv instead')

    def handle(self, *args, **opts):
        frames = self._from_csv() if opts['from_csv'] else self._from_yfinance(
            opts['tickers'] or DEFAULT_TICKERS, opts['period'])

        total = 0
        for symbol, df in frames:
            bars = [
                PriceBar(symbol=symbol, date=row.date, open=_dec(row.open), high=_dec(row.high),
                         low=_dec(row.low), close=_dec(row.close), volume=int(row.volume))
                for row in df.itertuples(index=False)
                if pd.notna(row.close) and pd.notna(row.volume)
            ]
            PriceBar.objects.bulk_create(bars, batch_size=5000, ignore_conflicts=True)
            total += len(bars)
            self.stdout.write(f'  {symbol}: {len(bars)} rows')

        # Refresh planner statistics so EXPLAIN ANALYZE reflects the new data.
        if connection.vendor == 'postgresql':
            with connection.cursor() as cur:
                cur.execute('ANALYZE price_bar;')
        self.stdout.write(self.style.SUCCESS(
            f'Processed {total} rows. price_bar now holds {PriceBar.objects.count()} rows.'))

    def _from_yfinance(self, tickers, period):
        import yfinance as yf
        self.stdout.write(f'Downloading {len(tickers)} tickers ({period}) from yfinance...')
        raw = yf.download(tickers, period=period, interval='1d', group_by='ticker',
                          auto_adjust=False, threads=True, progress=False)
        for symbol in tickers:
            try:
                df = raw[symbol] if len(tickers) > 1 else raw
            except KeyError:
                self.stdout.write(self.style.WARNING(f'  {symbol}: no data, skipped'))
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(-1)
            df = df.dropna(how='all')
            if df.empty:
                self.stdout.write(self.style.WARNING(f'  {symbol}: no data, skipped'))
                continue
            df = df.reset_index()
            df.columns = [str(c).lower() for c in df.columns]
            df = df.rename(columns={df.columns[0]: 'date'})  # index column is 'Date' or 'Datetime'
            df['date'] = pd.to_datetime(df['date']).dt.date
            yield symbol, df[['date', 'open', 'high', 'low', 'close', 'volume']]

    def _from_csv(self):
        for path in sorted(CSV_DIR.glob('*.csv')):
            df = pd.read_csv(path)
            df['date'] = pd.to_datetime(df['date']).dt.date
            yield path.stem.upper(), df[['date', 'open', 'high', 'low', 'close', 'volume']]
