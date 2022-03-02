#!/usr/bin/env python
#----------------------------------------------------------------------#
'''
A module to analyze token trends on the BSC blockchain.
This is very much a work in progress.
'''
#----------------------------------------------------------------------#
# System Module Imports
import os
import sys
import datetime
import configparser

# Additional Module Imports
import tqdm
import pandas as pd
import requests

# Local Imports

#----------------------------------------------------------------------#
# Read in my API keys from a config file
config = configparser.ConfigParser()
config.read(os.path.join(os.getenv('HOME'), '.config', 'api_keys.ini'))

#----------------------------------------------------------------------#
# BITQUERY API
#----------------------------------------------------------------------#

url_bitquery = 'https://graphql.bitquery.io'

#----------------------------------------------------------------------#
def run_query(query):  # A simple function to use requests.post to make the API call.
    headers = {'X-API-KEY': config['bitquery']['key']}
    request = requests.post(url_bitquery,
        json={'query': query}, headers=headers)
    if request.status_code == 200:
        return request.json()
    else:
        raise Exception('Query failed and return code is {}.      {}'.format(request.status_code, query))

#----------------------------------------------------------------------#
def q_pancake_recent_daily(start):
    return '''{
  ethereum(network: bsc) {
    dexTrades(
      options: {limit: 10000, desc: "trades"}
      date: {since: "%s"}
      exchangeName: {in: ["Pancake", "Pancake v2"]}
      quoteCurrency: {is: "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"}
    ) {
      timeInterval {
        day(count: 1)
      }
      baseCurrency {
        symbol
        address
      }
      baseAmount
      quoteCurrency {
        symbol
        address
      }
      quoteAmount
      trades: count
      quotePrice
      open_price: minimum(of: block, get: quote_price)
      high_price: quotePrice(calculate: maximum)
      low_price: quotePrice(calculate: minimum)
      close_price: maximum(of: block, get: quote_price)
    }
  }
}
''' % (start,)

#----------------------------------------------------------------------#
def q_ohlc_periods(
    address,
    start,
    period= 'minute',
    periods_per_candle= 1,
    limit_candles= None,
    quote_address= '0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c'):
    'Construct a query to obtain OHLC data for a given address.'
    
    # Apply the limit if one was given
    limit = (limit_candles is not None) and f'options: {{limit: {limit_candles}, asc: "timeInterval.{period}"}}' or ''
    
    # Now construct and return the query
    return '''{
  ethereum(network: bsc) {
    dexTrades(%s
      date: {since: "%s"}
      exchangeName: {in: ["Pancake", "Pancake v2"]}
      baseCurrency: {is: "%s"}
      quoteCurrency: {is: "%s"}
    ) {
      timeInterval {
        %s(count: %s)
      }
      baseCurrency {
        symbol
        address
      }
      trades: count
      open_price: minimum(of: block, get: quote_price)
      high_price: quotePrice(calculate: maximum)
      low_price: quotePrice(calculate: minimum)
      close_price: maximum(of: block, get: quote_price)
    }
  }
}
''' % (limit, start, address, quote_address, period, periods_per_candle)

#----------------------------------------------------------------------#
def q_tokens_created(start_time, end_time):
    return '''{
  ethereum(network: bsc) {
    smartContractCalls(
      options: {asc: "block.height", limit: 2147483647}
      smartContractMethod: {is: "Contract Creation"}
      smartContractType: {is: Token}
      time: {after: "%s", before: "%s"}
    ) {
      transaction {
        hash
      }
      block {
        height
        timestamp {
          iso8601
        }
      }
      smartContract {
        contractType
        address {
          address
          annotation
        }
        currency {
          name
          symbol
          decimals
          tokenType
        }
      }
      caller {
        address
      }
    }
  }
}
''' % (start_time, end_time)

#----------------------------------------------------------------------#
def get_recent_tokens(from_days_ago= 5, to_days_ago= 4):
    'Find all tokens registered within a given time period.'
    
    # Construct the query
    now    = datetime.datetime.now()
    start  = now - datetime.timedelta(days=from_days_ago)
    end    = now - datetime.timedelta(days=  to_days_ago)
    query  = q_tokens_created(start.isoformat(), end.isoformat())
    
    # Now run the query
    result = run_query(query)
    
    # Basic error handling
    if 'errors' in result:
        raise RuntimeError(f'ERROR: New tokens query failed with {result["errors"]}')
    
    # Collect info on each new token
    new_tokens = [
        {
            'created'   : datetime.datetime.fromisoformat(record['block']['timestamp']['iso8601'].rstrip('Z')),
            'owner'     : record['caller']['address'],
            'address'   : record['smartContract']['address']['address'],
            'decimals'  : record['smartContract']['currency']['decimals'],
            'name'      : record['smartContract']['currency']['name'],
            'symbol'    : record['smartContract']['currency']['symbol'],
            'tokenType' : record['smartContract']['currency']['tokenType'],
        }
        for record in result['data']['ethereum']['smartContractCalls']
    ]
    return new_tokens

#----------------------------------------------------------------------#
def float_nan(value):
    if value is None:
        return float('nan')
    return float(value)

#----------------------------------------------------------------------#
def get_ohlc(address, start_time, period= 'minute', periods_per_candle= 1, limit_candles= 24*60, quote_address= '0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c'):
    'Obtain OHLC data on an address.'
    
    # Construct and run a query to get OHLC data
    query  = q_ohlc_periods(address, start_time, period, periods_per_candle, limit_candles, quote_address)
    result = run_query(query)
    
    # Basic error handling
    if 'errors' in result:
        raise RuntimeError(f'ERROR: OHLC query ({address}, {start_time}, {period}, {periods_per_candle}, {limit_candles}) failed with {result["errors"]}')
    
    trades  = result['data']['ethereum']['dexTrades']
    times   = [pd.Timestamp(trade['timeInterval']['minute']) for trade in trades]
    ohlc    = [
        (
            float(trade['open_price']),
            (trade['high_price'] is None) and max(float(trade['open_price']),float(trade['close_price'])) or float(trade['high_price']),
            (trade['low_price']  is None) and min(float(trade['open_price']),float(trade['close_price'])) or float(trade['low_price' ]),
            float(trade['close_price']),
            int(trade['trades']),
        )
        for trade in trades
    ]
    ohlc_df = pd.DataFrame(ohlc, columns= ['open', 'high', 'low', 'close', 'trades'], index= times)
    return ohlc_df

#----------------------------------------------------------------------#
class OHLCData(dict):
    '''
    A class that obtains OHLC data from whatever source, can save/load as JSON, and can update on demand.
    It calculates a list of statistical indicators. Supported indicator types are:
        ema       : exponential moving average - alpha is controlled by number of periods in window
        crossover : abs=# periods since the last time val-a went up over val-b, sign=current comparison
    '''
    start_date    = None
    data          = None
    token_address = '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'
    quote_address = '0xe9e7cea3dedca5984780bafc599bd69add087d56'
    
    def __init__(self, token_address= None, quote_address= None, start_date= '2022-02-10', today= False):
        self.today = today and 1 or 0
        if token_address is not None:
            self.token_address = token_address
        if quote_address is not None:
            self.quote_address = quote_address
        self.start_date = start_date
        self.otherdata = {}
        self.load()
        self.retrieve()
        return
    
    def __len__(self):
        return self.data is not None and len(self.data) or 0
    
    def __contains__(self, key):
        if self.data is None:
            return False
        try:
            return len(self.data.loc[key]) > 0
        except:
            pass
        return False
    
    def __getitem__(self, key):
        if self.data is None:
            raise IndexError('Empty data')
        if isinstance(key, slice):
            try:
                return self.data[key]
            except:
                pass
            try:
                return self.data.loc[key]
            except:
                pass
            raise IndexError(f'Unable to process slice [{key}]')
        if key in self.data:
            return self.data[key]
        if key in self.data.index:
            return self.data.loc[key]
        raise IndexError(f'Unable to process query [{key}]')
    
    def __repr__(self):
        return f'OHLCData({repr(self.data)})'
    
    def __str__(self):
        return str(self.data)
    
    def save(self, verbose= True):
        'Save OHLC data and stats to a file.'
        if self.data is None:
            return
        try:
            self.data.to_pickle(f'ohlc_{self.token_address}_{self.quote_address}.pickle'.lower())
            if verbose:
                print(f'Saved {int(len(self.data) / 1440)} days of OHLC to storage file')
        except Exception as err:
            print(f'Unable to save storage file: {err}')
        return
    
    def load(self, verbose= True):
        'Load OHLC data and stats from a file.'
        try:
            self.data = pd.read_pickle(f'ohlc_{self.token_address}_{self.quote_address}.pickle'.lower())
            if verbose:
                print(f'Loaded {int(len(self.data) / 1440)} days of OHLC from storage file')
        except Exception as err:
            print(f'Unable to load storage file: {err}')
        return

    def retrieve(self):
        'Retrieve any missing data, and calculate stats over all data.'
        
        # Figure out what dates we will loop over
        date     = datetime.date.fromisoformat(self.start_date)
        day      = datetime.timedelta(days= 1)
        now      = datetime.datetime.now()
        today    = now.date()
        n_days   = self.today + int((today - date) / day)
        n_pulled = 0
        n_saved  = 0
        
        # Include any existing data we may have
        if self.data is not None:
            frames = [self.data]
        else:
            frames = []
        
        print('Retrieving data:')
        dates = tqdm.tqdm(range(n_days))
        for ii in dates:
            # Pull each day worth of OHLC from the server
            isodate = date.isoformat()
            dates.set_description(f'OHLC data [{isodate}] pulled={n_pulled:4} saved={n_saved:4} ')
            if isodate not in self or today == date:
                frames.append(get_ohlc(self.token_address, isodate, 'minute', 1, 24*60, self.quote_address))
                n_pulled += 1
                if n_pulled > 27:
                    self.data = pd.concat(frames)
                    self.save(False)
                    frames    = [self.data]
                    n_saved  += n_pulled
                    n_pulled  = 0
            
            date += day
        
        # Save the result
        if frames:
            self.data = pd.concat(frames)
        self.save()
        return
    
#----------------------------------------------------------------------#
class OHLCStats(object):
    def __init__(self, ohlc_data, ema_spans= [10, 20, 60, 120]):
        self.spans = ema_spans
        self.data  = ohlc_data
        self.emas  = pd.DataFrame(index=self.data.index)
        self.cross = pd.DataFrame(index=self.data.index)
        self.calc_emas()
        self.calc_crossings()
        return
    
    def calc_emas(self):
        fudge = {
            'high' : self.data[['open','close']].max(axis=1),
            'low'  : self.data[['open','close']].min(axis=1),
        }
        for span in self.spans:
            for col in ('high', 'low'):
                self.emas[f'ema_{col}_{span}'] = fudge[col].ewm(span=span).mean()
        return
    
    def calc_crossings(self):
        cols = [(self.data, col) for col in ('high', 'low')] + [(self.emas, col) for col in self.emas]
        minute = pd.Timedelta(minutes=1)
        self.mask_up = {}
        for frame_a, col_a in cols:
            for frame_b, col_b in cols:
                if col_a == col_b or frame_a is self.data and frame_b is self.data:
                    continue
                key = f'xover_[{col_a}]_[{col_b}]'
                # Detect if col_a was previously below col_b but not now
                mask_up = frame_a[col_a].shift().lt(frame_b[col_b]) & frame_a[col_a].ge(frame_b[col_b])
                
                # If that never happens, ignore this pair
                if (mask_up == False).all():
                    continue

                # Find the indices where this occurs
                self.cross[key] = mask_up.index.where(mask_up)

                # Elsewhere, fill in the last timestamp where it happened
                self.cross[key].fillna(method='ffill', inplace=True)

                # Take the difference and divide by minutes
                self.cross[key] = (self.cross.index - self.cross[key]) / minute
        return


#----------------------------------------------------------------------#
def analyze_new_token(token):
    'Perform basic trend analysis on a new token.'
    
    # Construct and run a query to get OHLC data
    ohlc = get_ohlc(token['address'], token['created'].isoformat(), 'minute', 1)
    
    # TBD...
    
    return ohlc
    
    
#----------------------------------------------------------------------#
def analysis():

    return get_recent_tokens()