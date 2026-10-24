import unittest
from unittest.mock import patch,Mock
from urllib.parse import urlparse,parse_qs
import json
import geocoding

class GeocodingTests(unittest.TestCase):
    def setUp(self):geocoding._lookup.cache_clear()
    def test_invalid_input_does_not_send(self):
        with patch('geocoding.urlopen') as fetch:
            for value in (None,10115,'1234','123456','abcde','1234ß','１２３４５','Main Street'):
                with self.assertRaises(ValueError):geocoding.lookup(value)
            fetch.assert_not_called()
    def test_filters_country_exact_postcode_and_bad_coordinates(self):
        row={'place name':'Ort','latitude':'51.1','longitude':'10.2','state':'Land'}
        rows=[row,row,{**row,'latitude':'NaN'},{**row,'latitude':True},{**row,'place name':'Ort 2','longitude':'10.3'}]
        data={'country abbreviation':'DE','post code':'01234','places':rows}
        result=geocoding.parse('01234',data)
        self.assertEqual(len(result),2);self.assertEqual(result[0]['postcode'],'01234')
        self.assertEqual(result[0]['name'],'Ort · Land')
        self.assertEqual(geocoding.parse('01234',{**data,'country abbreviation':'AT'}),[])
        self.assertEqual(geocoding.parse('01234',{**data,'post code':'12340'}),[])
    def test_lookup_keeps_leading_zero_and_caches(self):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=json.dumps({'country abbreviation':'DE','post code':'01234','places':[{'place name':'Ort','latitude':'51','longitude':'10'}]}).encode()
        with patch('geocoding.urlopen',return_value=response) as fetch:
            self.assertEqual(geocoding.lookup(' 01234 ')[0]['postcode'],'01234')
            geocoding.lookup('01234');self.assertEqual(fetch.call_count,1)
            self.assertEqual(fetch.call_args.args[0],'https://api.zippopotam.us/de/01234')
    def test_unknown_postcode_404_is_empty(self):
        from urllib.error import HTTPError
        with patch('geocoding.urlopen',side_effect=HTTPError('url',404,'Not found',{},None)):
            self.assertEqual(geocoding.lookup('00000'),[])
    def test_timeout_error_is_actionable(self):
        with patch('geocoding.urlopen',side_effect=TimeoutError):
            with self.assertRaisesRegex(ValueError,'erneut versuchen'):geocoding.lookup('10115')
    def test_empty_results(self):self.assertEqual(geocoding.parse('10115',{}),[])
