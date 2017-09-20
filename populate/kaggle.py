""" Get CSVs from https://www.kaggle.com/mczielinski/bitcoin-historical-data
Note there's a lot of nulls in there, see my empty-handling below & determine if right way to go.
"""

import pandas as pd
import numpy as np
from sqlalchemy import create_engine

engine = create_engine("postgres://lefnire:lefnire@localhost:5432/kaggle")
conn = engine.connect()

column_renames = {
    'Timestamp': 'timestamp',
    'Open': 'open',
    'High': 'high',
    'Low': 'low',
    'Close': 'close',
    'Volume_(BTC)': 'volume_btc',
    'Volume_(Currency)': 'volume_currency',
    'Weighted_Price': 'weighted_price'
}

for filename in ['bitstamp', 'btcn', 'btce']:
    df = pd.read_csv(f'../tmp/kaggle/{filename}.csv')
    df = df.rename(columns=column_renames)

    # Fill empty values. TODO make sure this is correct! Simple solution is `df = df.ffill()`
    df.close = df.close.ffill()
    for k in ['open', 'high', 'low']:
        df[k] = df[k].fillna(df.close)
    for k in ['volume_btc', 'volume_currency', 'weighted_price']:
        df[k] = df[k].fillna(0)

    print(f'{filename}: saving to DB')
    df.to_sql(filename, conn, if_exists='replace')

    print(f'{filename}: modifying columns')
    conn.execute(f"""
    ALTER TABLE {filename} ALTER timestamp TYPE TIMESTAMP WITH TIME ZONE USING to_timestamp(timestamp) AT TIME ZONE 'UTC';
    CREATE INDEX {filename}_timestamp ON {filename} (timestamp);
    """)
    print(f'{filename}: done')
