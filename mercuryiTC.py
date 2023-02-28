import logging
from time import sleep
from tqdm import tqdm
import numpy as np
from qcodes.instrument.visa import VisaInstrument
from qcodes.utils import validators as vals

log = logging.getLogger(__name__)

class MercuryiTC(VisaInstrument):
    """
    @Author: David Barcons (ICFO, Barcelona, Feb 2023)
    
    This is a qcodes driver for the Oxford MercuryiTC.
    The temperature controller is used to control the Oxford Instruments Spectromag cryostat
    with a base temperature of 1.6K.
    The driver is written as an VisaInstrument
    It allows to control the probe temperature in an fully automatized manner.

    Args:
        name (str): name of the instrument
        address (str): The USB address of the instrument e.g. ASRL4::INSTR
        adresses of the iTC modules (str): 

    Version 1.0. Tested.

    Todo::
    
    - Write an automatic procedure to cooldown controlling the needle valve
    
    How to use:
    - To read the probe temperature:
        self.probe_temp()
    - To set a temperature, and wait until it is reached:
        self.probe_temp(T)
    - To read/set the heater rate (K/min):
        self.heater_rate()

    """
    def __init__(self, name, address, probe_temp = 'DEV:DB8.T1:TEMP', probe_heater = 'DEV:DB3.H1:HTR', 
                pressure = 'DEV:DB5.P1:PRES', needle_valve = 'DEV:DB4.G1:AUX', vti_temp = 'DEV:MB1.T1:TEMP', vti_heater = 'DEV:MB0.H1:HTR', **kwargs):
        super().__init__(name, address, terminator='\n',
                         **kwargs)
        # Coding here could be simplified.
        self.probe_heater_str = probe_heater
        self.probe_temp_str = probe_temp 
        self.pressure_str = pressure
        self.needle_valve_str = needle_valve
        self.vti_temp_str = vti_temp
        self.vti_heater_str = vti_heater
        
        # Check all sensors are present, otherwise output an error
        self.modules = [self.probe_heater_str, self.probe_temp_str, self.pressure_str, self.needle_valve_str, self.vti_temp_str, self.vti_heater_str]
        for mod in self.modules:
            self.nick = self.ask('READ:' + mod + ':NICK?')
            if (self.nick[-7:] == 'INVALID'):
                raise Exception("Input the correct modules addresses: " + str(self.ask('READ:SYS:CAT')))
               
        # Probe temperature parameters
        # Assign probe heater, vti heater and needle_valve to the temperature control loop.      

        self.ask('SET:' + self.probe_temp_str + ':LOOP:HTR:' + self.probe_heater_str.split(':')[1])
        self.ask('SET:' + self.probe_temp_str + ':LOOP:AUX:' + self.needle_valve_str.split(':')[1])
        self.ask('SET:' + self.vti_temp_str + ':LOOP:HTR:' + self.vti_heater_str.split(':')[1])
        
        self.add_parameter('probe_temp',
                           label='Probe Temperature',
                           unit='K',
                           docstring='Temperature of the probe sensor (D1)',
                           get_cmd="READ:" + self.probe_temp_str + ":SIG:TEMP?",
                           get_parser=self._temp_parser,
                           set_cmd=lambda x: self.set_temp_and_block(x),
                           vals=vals.Numbers(min_value=1.6, max_value=300) 
                           )
        self.add_parameter('vti_temp',
                           label='VTI Temperature',
                           unit='K',
                           docstring='Temperature of the VTI',
                           get_cmd="READ:" + self.vti_temp_str + ":SIG:TEMP?",
                           get_parser=self._temp_parser,
                           set_cmd=lambda x: self._set_vti_temp(x),
                           )
                           
        self.add_parameter('temp_loop_P',
                           label='loop P',
                           get_cmd='READ:' + self.probe_temp_str + ':LOOP:P?',
                           get_parser=self._float_parser_nounits,
                           set_cmd = lambda x: self.ask('SET:' + self.probe_temp_str + f':LOOP:P:{x}'),
                           )
                           
        self.add_parameter('temp_loop_I',
                           label='loop I',
                           get_cmd='READ:' + self.probe_temp_str + ':LOOP:I?',
                           get_parser=self._float_parser_nounits,
                           set_cmd = lambda x: self.ask('SET:' + self.probe_temp_str + f':LOOP:I:{x}'),
                           )
                           
        self.add_parameter('temp_loop_D',
                           label='loop D',
                           get_cmd='READ:' + self.probe_temp_str + ':LOOP:D?',
                           get_parser=self._float_parser_nounits,
                           set_cmd = lambda x: self.ask('SET:' + self.probe_temp_str + f':LOOP:D:{x}'),
                           )
        
        self.add_parameter('temp_PID_auto',
                           label='PID auto mode',
                           get_cmd='READ:' + self.probe_temp_str + ':LOOP:ENAB?',
                           get_parser=self._str_parser,
                           set_cmd = lambda x: self.ask('SET:' + self.probe_temp_str + ':LOOP:ENAB:' + str(x))
                           )
                           
        self.add_parameter('vti_temp_PID_auto',
                           label='VTI PID auto mode',
                           get_cmd='READ:' + self.vti_temp_str + ':LOOP:ENAB?',
                           get_parser=self._str_parser,
                           set_cmd = lambda x: self.ask('SET:' + self.vti_temp_str + ':LOOP:ENAB:' + str(x))
                           )
                           
        self.add_parameter('temp_PID_fromtable',
                           label='PID from table',
                           get_cmd='READ:' + self.probe_temp_str + ':LOOP:PIDT?',
                           get_parser=self._str_parser,
                           set_cmd = lambda x: self.ask('SET:' + self.probe_temp_str + ':LOOP:PIDT:' + str(x))
                           )

        self.add_parameter('temp_setpoint',
                           label='Heater Temperature Setpoint',
                           unit='K',
                           docstring='Temperature setpoint for the heater',
                           get_cmd='READ:' + self.probe_temp_str + ':LOOP:TSET?',
                           get_parser=self._temp_parser,
                           set_cmd=lambda x: self.ask('SET:' + self.probe_temp_str + f':LOOP:TSET:{x}')
                           )

        self.add_parameter('heater_ramp_mode',
                           label='Heater Ramp Mode',
                           get_cmd='READ:' + self.probe_temp_str + ':LOOP:RENA?',
                           get_parser=self._str_parser,
                           set_cmd=lambda x: self.ask('SET:' + self.probe_temp_str + ':LOOP:RENA:' + str(x))
                           )

        self.add_parameter('heater_rate',
                           label='Heater Rate in K/min',
                           unit='K/min',
                           docstring='Temperature setpoint for the heater',
                           get_cmd='READ:' + self.probe_temp_str + ':LOOP:RSET?',
                           get_parser=self._rate_parser,
                           set_cmd=lambda x: self.ask('SET:' + self.probe_temp_str + f':LOOP:RSET:{x}')
                           )
                           
        self.add_parameter('vti_temp_setpoint',
                           label='VTI heater Temperature Setpoint',
                           unit='K',
                           docstring='Temperature setpoint for the VTI heater',
                           get_cmd='READ:' + self.vti_temp_str + ':LOOP:TSET?',
                           get_parser=self._temp_parser,
                           set_cmd=lambda x: self.ask('SET:' + self.vti_temp_str + f':LOOP:TSET:{x}')
                           )

        self.add_parameter('vti_heater_ramp_mode',
                           label='VTI heater Ramp Mode',
                           get_cmd='READ:' + self.vti_temp_str + ':LOOP:RENA?',
                           get_parser=self._str_parser,
                           set_cmd=lambda x: self.ask('SET:' + self.vti_temp_str + ':LOOP:RENA:' + str(x))
                           )

        self.add_parameter('vti_heater_rate',
                           label='VTI heater Rate in K/min',
                           unit='K/min',
                           docstring='VTI temperature setpoint for the VTI heater',
                           get_cmd='READ:' + self.vti_temp_str + ':LOOP:RSET?',
                           get_parser=self._rate_parser,
                           set_cmd=lambda x: self.ask('SET:' + self.vti_temp_str + f':LOOP:RSET:{x}')
                           )

        self.add_parameter('flow_auto_mode',
                           label='Flow auto mode',
                           get_cmd='READ:' + self.probe_temp_str + ':LOOP:FAUT?',
                           get_parser=self._str_parser,
                           set_cmd=lambda x: self.ask('SET:' + self.probe_temp_str + f':LOOP:FAUT:' + str(x))
                           )

        self.add_parameter('vti_pressure',
                           label='VTI pressure',
                           unit='mbar',
                           get_cmd="READ:" +self.pressure_str +":SIG:PRES?",
                           get_parser=self._pressure_parser
                           )
                           
        self.connect_message()
        
        # set a default heater ramp rate.
        self.heater_rate(5.0)
        self.vti_heater_rate(5.0)        

    ###########
    # Parsers #
    ###########
   
    def _float_parser_nounits(self, value: str):
        return float(value.split(':')[-1])  # Return the number after the equals as a float
    
    def _str_parser(self, value: str):
        return value.split(':')[-1]  # Return the number after the : as a string
    
    def _pressure_parser(self, value: str):
        return float(value.split(':')[-1][:-2])  # Return the number after the : as a float
        
    def _rate_parser(self, value: str):
        return float(value.split(':')[-1][:-3])  # Return the number after the : as a float
        
    def _temp_parser(self, value: str):
        return float(value.split(':')[-1][:-1])  # Return the number after the : as a float

    #########################
    # Temperature functions #
    #########################

    def _set_all_auto(self):
        self.temp_PID_auto('ON')
        self.vti_temp_PID_auto('ON')
        self.flow_auto_mode('ON')

    def _config_heater_default(self):
        self.temp_loop_P(25.0)
        self.temp_loop_I(1.0)
        self.temp_loop_D(0.0)
        self.temp_PID_auto('ON')

    def _safe_set_temp(self, sp): 
        # set all auto and default PID values
        self._config_heater_default()
        self._set_all_auto()
        sleep(1)
        self.heater_ramp_mode('ON')  # turn ramp mode on
        self.temp_setpoint(sp)  # set desired setpoint on the heater
        sleep(1)
        self.device_clear()
        sleep(2)

    def block_until_temp(self, target, precision=0.05, p=False):
        """
        Blocks the script until the temperature reaches a target value, with a precision that is 50 mK by default
        """
        try:
            self.device_clear()
            sleep(2)
            start = self.probe_temp()
            while abs(self.probe_temp() - target) > abs(precision):
                if p:
                    self._print_temp_status(start, self.probe_temp.cache(), target)
        except TypeError:
            print('Heater has no setpoint')

    def _print_temp_status(self, start, current, stop):
        status = abs((start - current) / (start - stop))
        if status < 1:
            tqdm.write(f"Temperature ramp {status*100:.1f}% done" + 30 * ' ', end='\r')
        else:
            tqdm.write('Waiting for temperature stabilization' + 30 * ' ', end='\r')

    def set_temp_and_block(self, target, precision=0.05):
        vti_target = self._calculate_vti_temp(target)
        self._safe_set_temp(target)
        self._set_vti_temp(vti_target)
        self.block_until_temp(target, precision=precision, p=True)
        
    def _set_vti_temp(self, target):

        # set all auto and default PID values
        self._set_all_auto()
        sleep(1)
        self.vti_heater_ramp_mode('ON')  # turn ramp mode on
        self.vti_temp_setpoint(target)  # set desired setpoint on the heater
        sleep(1)
        self.device_clear()

    def _calculate_vti_temp(self, probe_temp):
        """
        Function to calculate the optimium VTI temperature setpoint as a functions
        of the probe temperature setpoint, as described in the Spectromag manual.
        """
        self.vti_list = np.array([1.6, 1.65, 5.9, 9.8, 19.5, 48.0, 97.0, 195.0, 295.0])
        self.probe_list = np.array([1.6, 1.7, 6, 10, 20, 50, 100, 200, 300])
        vti_temp_target = np.interp(probe_temp, self.probe_list, self.vti_list)
        return vti_temp_target
        
    def cooldown_to_base(self):
        self.vti_temp_setpoint(1.6)
        self.temp_setpoint(1.6)
        self.vti_heater_ramp_mode('OFF')
        self.heater_ramp_mode('OFF')

