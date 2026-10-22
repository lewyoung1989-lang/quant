"""The Demo bridge submits intent to real services, using isolated accounts and quotes."""
import os
import tempfile
import unittest
from unittest.mock import patch

from services.simulation_store import AccountError, SimulationStore, defaults, now
from ui.simulation_component import dispatch, snapshot, frontend_config


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'QUANT_PROFILE_DIR': self.temp.name, 'QUANT_DISABLE_WORKER': '1'})
        self.env.start()
        self.store = SimulationStore(self.temp.name)
        self.account = self.store.create('界面验证账户', 100000, 'rotation', defaults('rotation'))

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def command(self, action, **kwargs):
        return dispatch(self.store, dict(action=action, requestId='test-'+action, accountId=self.account['id'], **kwargs))

    def test_create_configure_and_pause_keep_account_identity(self):
        result=self.command('create', name='前端创建', capital=200000, strategy='rotation', config={'attack':'sh588380','defense':'sh511010','lookback':30}, auto=False, feeRate=.0001)
        created=self.store.get(result['accountId'])
        self.assertEqual(created['cash_available'],200000)
        self.assertEqual(created['parameters']['lookback_window'],30)
        self.assertFalse(created['auto_trade'])
        self.command('configure', revision=1, name='已更名', strategy='erp', config={'low':20,'high':80,'lowWeight':50,'midWeight':75,'highWeight':100}, auto=True, feeRate=.0002)
        self.command('pause', revision=2, running=False)
        updated=self.store.get(self.account['id'])
        self.assertEqual(updated['name'],'已更名')
        self.assertEqual(updated['strategy_type'],'dividend_erp')
        self.assertEqual(updated['cash_available'],100000)
        self.assertTrue(updated['auto_trade'])
        self.assertFalse(updated['running'])

    def test_erp_defense_bridge_persists_choice(self):
        self.command('configure',revision=1,name='防守配置',strategy='erp',
                     config={'low':20,'high':35,'lowWeight':0,'midWeight':50,'highWeight':100,'defense':'sh511260'},auto=False,feeRate=.0003)
        account=self.store.get(self.account['id'])
        self.assertEqual(account['parameters']['defensive_asset'],'sh511260')
        self.assertEqual(frontend_config(account)['defense'],'sh511260')

    def test_realtime_observation_does_not_replace_execution_signal(self):
        a=self.store.create('双信号',100000,'dividend_erp',{**defaults('dividend_erp'),'execution_mode':'next_open'})
        quotes={symbol:{'price':100.,'open':100.,'quote_time':now().isoformat()} for symbol in ['sh588380','sh511010','sh512890','sh511260']}
        def signal(strategy,params,*args):
            return {'valid':True,'target_symbol':'sh512890','weight':0.,'erp':10.,'erp_pct':.068 if params.get('execution_mode')=='next_open' else .12,'historical_asof':'2026-10-19','band':'测试'}
        with patch('ui.simulation_component.live_quotes',return_value=quotes),patch('ui.simulation_component.cached_signal',side_effect=signal):
            row=next(r for r in snapshot(self.store,a['id'])['accounts'] if r['id']==a['id'])
        self.assertEqual(row['observation']['live']['erp_pct'],.12)
        self.assertEqual(row['observation']['confirmed']['erp_pct'],.068)
        self.assertEqual(row['plan']['signal']['erp_pct'],.068)
        self.assertEqual(self.store.get(a['id'])['parameters']['execution_mode'],'next_open')

    def test_funds_retry_and_stale_drawer_revision(self):
        self.command('funds',revision=1,amount=25000,withdraw=False)
        self.command('funds',revision=1,amount=25000,withdraw=False)
        self.assertEqual(self.store.get(self.account['id'])['cash_available'],125000)
        with self.assertRaises(AccountError):
            dispatch(self.store,dict(action='funds',requestId='new',accountId=self.account['id'],revision=1,amount=1000,withdraw=False))

    def test_client_cannot_supply_own_fill_or_price(self):
        with patch('ui.simulation_component.execute_plan',return_value={'message':'done'}) as execute, patch('ui.simulation_component.refresh_quotes'):
            self.command('execute',planId='reviewed-plan',quotes={'fake':1},cash=1e9,at='2026-10-16T14:50:00')
        execute.assert_called_once_with(self.store,self.account['id'],'reviewed-plan','manual:reviewed-plan')

    def test_snapshot_uses_real_records_and_preserves_missing_prices(self):
        self.store.transfer(self.account['id'],1,20000)
        with patch('ui.simulation_component.live_quotes',return_value={}):
            data=snapshot(self.store)
        a=data['accounts'][0]
        self.assertEqual(a['cash'],120000)
        self.assertFalse(a['plan']['canExecute'])
        self.assertIsNone(a['plan']['signal'])
        self.assertEqual(len(a['funds']),2)
        self.assertEqual(a['config']['attack'],'sh588380')

    def test_navigation_whitelist_and_unknown_strategy(self):
        self.assertEqual(self.command('navigate',mode='因子实验')['navigate'],'因子实验')
        with self.assertRaises(AccountError):self.command('navigate',mode='arbitrary')
        with self.assertRaises(AccountError):self.command('create',strategy='unknown',config={})


if __name__=='__main__':unittest.main()
