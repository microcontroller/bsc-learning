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
def get_ohlc(address, start_time, period= 'minute', periods_per_candle= 1, limit_candles= 24*60, quote_address= '0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c'):
    'Obtain OHLC data on an address.'
    
    # Construct and run a query to get OHLC data
    query  = q_ohlc_periods(address, start_time, period, periods_per_candle, limit_candles, quote_address)
    result = run_query(query)
    
    # Basic error handling
    if 'errors' in result:
        raise RuntimeError(f'ERROR: OHLC query ({address}, {start_time}, {period}, {periods_per_candle}, {limit_candles}) failed with {result["errors"]}')
    
    trades = result['data']['ethereum']['dexTrades']
    ohlc   = [
        (
            trade['open_price'],
            trade['high_price'],
            trade['low_price'],
            trade['close_price'],
            trade['timeInterval']['minute'],
            trade['trades'],
        )
        for trade in trades
    ]
    return ohlc

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