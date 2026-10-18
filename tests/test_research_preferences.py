import datetime as dt
import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

class ResearchPreferenceTests(unittest.TestCase):
    def test_fresh_session_restores_parameters_and_isolates_strategy(self):
        code = '''
import datetime as dt
from ui.research_preferences import ResearchPreferences
p=ResearchPreferences('红利')
p.slider('仓位',min_value=0,max_value=100,value=50,step=5)
p.selectbox('标的',['A','B'])
p.date_input('区间',(dt.date(2020,1,1),dt.date(2021,1,1)))
p.text_area('表达式',value='x')
'''
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ',{'QUANT_PROFILE_DIR':root}):
            a=AppTest.from_string(code).run()
            a.slider[0].set_value(75).run()
            a.selectbox[0].select('B').run()
            a.date_input[0].set_value((dt.date(2022,1,1),dt.date(2023,1,1))).run()
            a.text_area[0].set_value('y').run()
            b=AppTest.from_string(code).run()
            self.assertFalse(b.exception)
            self.assertEqual(b.slider[0].value,75)
            self.assertEqual(b.selectbox[0].value,'B')
            self.assertEqual(b.text_area[0].value,'y')
            self.assertEqual(b.date_input[0].value,(dt.date(2022,1,1),dt.date(2023,1,1)))
            c=AppTest.from_string(code.replace("ResearchPreferences('红利')","ResearchPreferences('轮动')")).run()
            self.assertEqual(c.slider[0].value,50)
