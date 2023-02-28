import logging
import time
from tqdm import tqdm
import numpy as np
from qcodes.instrument.visa import VisaInstrument
from qcodes.utils import validators as vals

log = logging.getLogger(__name__)
visalog = logging.getLogger('qcodes.instrument.visa')

class MercuryiPS(VisaInstrument):
    """
    @Author: David Barcons (ICFO, Barcelona, Feb 2023)
    
    This is a qcodes driver for the Oxford MercuryiPS.
    The driver is written as an VisaInstrument
    It allows to sweep the magnetic field in an fully automatized manner.

    Args:
        name (str): name of the instrument
        address (str): The VISA resource of the instrument. Note that a
        socket connection to port 7020 must be made 

    Version 1.0. Tested.

    """

    def __init__(self, name: str, address: str,  **kwargs) -> None:


        super().__init__(name, address, terminator='\n',
                         **kwargs)
        #Set magnet quench temperature default limit
        self.t_limit = 5.0
        #We only have z-axis magnet
        self.psu_string = 'PSU'
        self.uid = 'GRPZ'
        
        self.add_parameter('voltage',
                           label='Output voltage',
                           get_cmd=f'READ:DEV:{self.uid}:{self.psu_string}:SIG:VOLT',
                           unit='V',
                           get_parser=self._singleunit_parser)

        self.add_parameter('current',
                           label='Output current',
                           get_cmd=f'READ:DEV:{self.uid}:{self.psu_string}:SIG:CURR',
                           unit='A',
                           get_parser=self._singleunit_parser)

        self.add_parameter('current_persistent',
                           label='Output persistent current',
                           get_cmd=f'READ:DEV:{self.uid}:{self.psu_string}:SIG:PCUR',
                           unit='A',
                           get_parser=self._singleunit_parser)

        self.add_parameter('current_target',
                           label='Target current',
                           get_cmd=f'READ:DEV:{self.uid}:{self.psu_string}:SIG:CSET',
                           unit='A',
                           get_parser=self._singleunit_parser)

        self.add_parameter('field_target',
                           label='Target field',
                           unit='T',
                           get_cmd=f'READ:DEV:{self.uid}:{self.psu_string}:SIG:FSET',
                           set_cmd=lambda x: self.ask(f'SET:DEV:{self.uid}:{self.psu_string}:SIG:FSET:{str(x)}'),
                           get_parser=self._singleunit_parser)

        self.add_parameter('current_ramp_rate',
                           label='Ramp rate (current)',
                           unit='A/min',
                           get_cmd=f'READ:DEV:{self.uid}:{self.psu_string}:SIG:RCST',
                           get_parser=self._rate_parser)

        self.add_parameter('field_ramp_rate',
                           label='Ramp rate (field)',
                           unit='T/min',
                           set_cmd=lambda x: self.ask(f'SET:DEV:{self.uid}:{self.psu_string}:SIG:RFST:{str(x)}'),
                           get_cmd=f'READ:DEV:{self.uid}:{self.psu_string}:SIG:RFST',
                           get_parser=self._rate_parser)

        self.add_parameter('field',
                           label='Field strength',
                           unit='T',
                           get_cmd=f'READ:DEV:{self.uid}:{self.psu_string}:SIG:FLD',
                           get_parser=self._singleunit_parser,
                           set_cmd = lambda x: self.set_field_and_ramp_blocking(x),
                           vals=vals.Numbers(min_value = -7.0, max_value = 7.0))

        self.add_parameter('field_persistent',
                           label='Persistent field strength',
                           unit='T',
                           get_cmd=f'READ:DEV:{self.uid}:{self.psu_string}:SIG:PFLD',
                           get_parser=self._singleunit_parser)

        self.add_parameter('ATOB',
                           label='Current to field ratio',
                           unit='A/T',
                           get_cmd=f'READ:DEV:{self.uid}:{self.psu_string}:ATOB',
                           get_parser=self._rate_parser,
                           set_cmd=lambda x: self.ask(f'SET:DEV:{self.uid}:{self.psu_string}:ATOB:{str(x)}'))

        self.add_parameter('ramp_status',
                           label='Ramp status',
                           get_cmd=f'READ:DEV:{self.uid}:{self.psu_string}:ACTN',
                           get_parser=self._preparser,
                           set_cmd=lambda x: self.ask(f'SET:DEV:{self.uid}:{self.psu_string}:ACTN:{str(x)}'),
                           val_mapping={'HOLD': 'HOLD',
                                        'TO SET': 'RTOS',
                                        'CLAMP': 'CLMP',
                                        'TO ZERO': 'RTOZ'})
                                      
        self.add_parameter(name="temp",
                           label="Magnet Temperature",
                           unit="K",
                           get_cmd=f'READ:DEV:MB1.T1:TEMP:SIG:TEMP',
                           get_parser = self._singleunit_parser,
                           )
                           
        self.add_parameter(name="temp_limit",
                           label="Magnet temperature limit",
                           unit="K",
                           get_cmd=self.t_limit_reader,
                           set_cmd=lambda x: self.t_limit_setter(x),
                           )
        self.add_parameter(name="switch_heater",
                           label="Magnet switch_heater",
                           get_cmd=f'READ:DEV:{self.uid}:{self.psu_string}:SIG:SWHT',
                           get_parser=self._preparser,
                           set_cmd=lambda x: self.ask(f'SET:DEV:{self.uid}:{self.psu_string}:SIG:SWHT:{x}'),
                           )
                           
        self.connect_message()
        
    def _preparser(self, bare_resp: str) -> str:
        return bare_resp.split(':')[-1]
        
    def _singleunit_parser(self, value: str):
        return float(value.split(':')[-1][:-1])
        
    def _rate_parser(self, value: str):
        return float(value.split(':')[-1][:-3]) 
        
    def t_limit_setter(self, limit) -> None:
        self.t_limit = limit
        
    def t_limit_reader(self):
        return self.t_limit
    
    def switch_heater_on_and_wait(self) -> None:
        if (self.switch_heater()=='OFF'):
            self.switch_heater('ON')
            time.sleep(60*10)
    
    def set_field_and_ramp_blocking(self, target: float) -> None:
        """Convenient method to combine setting target and ramping"""
        if (self.switch_heater()=='OFF'):
            raise print('Switch heater is off. Use switch_heater_on_and_wait() function.')
        
        start = self.field()
        self.field_target(target)
        self.ramp_to_target()
        while self.ramp_status() == 'TO SET':
            if (self.temp() > self.temp_limit()):
                self.ramp_status('HOLD')
                raise ValueError('Magnet ramp stopped since its temperature'
                    'exceeded the safety limit:'
                    f'Temperature safety limit = {self.temp_limit()}'
                    f'Temperature reached = {self.temp()}')
            time.sleep(0.1)
            self._print_field_status(start, self.field(), target)
            
    def _print_field_status(self, start, current, stop):
        status = abs((start - current) / (start - stop))
        if status < 1:
            tqdm.write(f"Magnetic field ramp {status*100:.1f}% done" + 30 * ' ', end='\r')
        else:
            tqdm.write('Waiting for field stabilization' + 30 * ' ', end='\r')

    def ramp_to_target(self) -> None:
        """
        Unconditionally ramp this PS to its target
        """
        status = self.ramp_status()
        if status == 'CLAMP':
            self.ramp_status('HOLD')
        self.ramp_status('TO SET')
       