import ctypes
import unittest
from unittest.mock import Mock
import steam_achievements as steam

class SteamTests(unittest.TestCase):
    def fake(self):
        api = Mock(stats=123)
        api.request.return_value = True
        api.set.return_value = True
        api.store.return_value = True
        api.entries.side_effect = [[{'id':'ACH_TEST','unlocked':False}],
                                   [{'id':'ACH_TEST','unlocked':True}]]
        return api

    def test_read_only_never_mutates(self):
        api=self.fake()
        result=steam.operate(api,'list')
        self.assertFalse(result['write'])
        api.set.assert_not_called()
        api.store.assert_not_called()

    def test_confirmation_and_single_id(self):
        for value in [None,'','*','one,two','x/../y',['one','two']]:
            with self.assertRaises(ValueError):
                steam.validate_request('unlock',value,True)
        for confirmed in [False,None,1,'yes']:
            with self.assertRaises(ValueError):
                steam.validate_request('unlock','ACH_TEST',confirmed)
        steam.validate_request('unlock','ACH_TEST',True)

    def test_unknown_and_already_unlocked_never_mutate(self):
        api=self.fake()
        with self.assertRaises(ValueError):steam.operate(api,'unlock','OTHER')
        api.set.assert_not_called()
        api=self.fake();api.entries.side_effect=None
        api.entries.return_value=[{'id':'ACH_TEST','unlocked':True}]
        self.assertTrue(steam.operate(api,'unlock','ACH_TEST')['already_unlocked'])
        api.set.assert_not_called();api.store.assert_not_called()

    def test_one_unlock_store_callback_and_readback(self):
        api=self.fake()
        self.assertTrue(steam.operate(api,'unlock','ACH_TEST')['stored'])
        api.set.assert_called_once_with(123,b'ACH_TEST')
        api.store.assert_called_once_with(123)
        self.assertEqual([c.args[0] for c in api.wait.call_args_list],[1101,1102,1101])
        api=self.fake();api.store.return_value=False
        with self.assertRaises(ValueError):steam.operate(api,'unlock','ACH_TEST')
        api=self.fake();api.entries.side_effect=[[{'id':'ACH_TEST','unlocked':False}]]*2
        with self.assertRaises(ValueError):steam.operate(api,'unlock','ACH_TEST')

    def test_native_callback_layout_and_timeout(self):
        if ctypes.sizeof(ctypes.c_void_p)==8:
            self.assertEqual(ctypes.sizeof(steam.Callback),24)
            self.assertEqual(ctypes.sizeof(steam.StatsReceived),24)
            self.assertEqual(ctypes.sizeof(steam.StatsStored),16)
        api=object.__new__(steam.Steam);api.pipe=lambda:1
        with self.assertRaises(ValueError):api.wait(1101,steam.StatsReceived,0)
