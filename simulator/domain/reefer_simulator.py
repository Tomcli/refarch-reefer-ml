import csv, sys, json, datetime
import random
import numpy as np
import pandas as pd
import os

'''
Simulate the metrics for a Reefer container according to the type of simulation.
Each simulation type is a different method.
The variables that changes are Co2, O2, power and temperature

'''

# Define constants for "normal" values of columns
CO2_LEVEL = 4 # in percent
O2_LEVEL = 21 # in percent
NITROGEN_LEVEL = 0.78 # in percent
POWER_LEVEL= 7.2 # in kW
NB_RECORDS_IMPACTED = 7
MAX_RECORDS = 1000
DEFROST_LEVEL = 7


def _generateTimestamps(nb_records: int, start_time: datetime.datetime):
    '''
    Generate a timestamp column for a dataframe of results.

    Arguments:
        nb_records: Number of rows to generate
        start_time: Timestamp of first row, or None to use the current time.
            By convention, each subsequent row will be exactly 15 minutes later.

    Returns a Pandas Series object, suitable for use as a column or index
    '''
    if start_time is None:
        start_time = datetime.datetime.today() 
    return pd.date_range(start_time, periods=nb_records, freq="15min")


def _generateStationaryCols(nb_records: int, cid: str, content_type: int,
                            tgood: float):
    '''
    Generate the columns of the simulator output that can be generated by 
    stationary (stateless) processes.

    Note that the values of these columns may be replaced with values from
    a stateful generator later on in the data generation process.

    Arguments:
        nb_records: How many rows of data to generate
        cid: Container ID string
        content_type: integer key representing what's in the container, or
            None to have this function pick a random integer
        tgood: Target temperature

    Returns a Pandas dataframe with the indicated set of columns populated.
    '''
    content_type = random.randint(1, 5) if content_type is None else content_type
    cols = {}

    # Constant values
    cols["ID"] = np.repeat(cid, nb_records)
    cols["ContentType"] = np.repeat(content_type, nb_records)
    cols["Target_Temperature(celsius)"] = np.repeat(tgood, nb_records)

    # Normally-distributed floating-point values
    cols["O2"] = np.random.normal(O2_LEVEL, 3.0, size=nb_records)
    cols["CO2"] = np.random.normal(CO2_LEVEL, 3.0, size=nb_records)
    cols["Time_Door_Open"] = np.random.normal(30.0, 2.0, size=nb_records)
    cols["Temperature(celsius)"] = np.random.normal(tgood, 2.0, size=nb_records)
    cols["Power"] = np.random.normal(POWER_LEVEL, 6, size=nb_records)

    # Uniform values
    cols["Defrost_Cycle"] = np.random.randint(0, DEFROST_LEVEL, size=nb_records)

    return pd.DataFrame(data=cols)


def _simulatePowerOff(nb_records: int,
                      tgood: float):
    '''
    Run a state machine to simulate a container experiencing repeated power
    loss,

    Arguments:
        nb_records: Number of records to generate
        tgood: Mean temperature to generate when power is NOT off

    Returns a record containing multiple series. Key is series name, value is
    numpy array of series values. Series names:
    * Temperature
    * Maintenance_Required
    * Power
    * PowerConsumption
    '''
    new_temp = np.ndarray(nb_records, dtype=np.float64)
    new_maint_req = np.ndarray(nb_records, dtype=int)
    new_power = np.ndarray(nb_records, dtype=np.float64)
    new_power_consumption = np.ndarray(nb_records, dtype=np.float64)

    # TODO: Clean up the logic here
    temp = random.gauss(tgood, 3.0)    
    count_pwr = 0  # generate NB_RECORDS_IMPACTED records with power off
    pwrc = 0
    for i in range(nb_records):
        oldtemp = temp
        temp =  random.gauss(tgood, 2.0)

        pwr = random.gauss(POWER_LEVEL, 6)
        if pwrc == 0:
            pwrc = random.gauss(POWER_LEVEL, 10.0)
        else:
            # TODO: This equation is wrong! Should be pwr + pwrc * hours 
            pwrc = pwr + pwrc

        # as soon as one amp record < 0 then poweroff for n records
        maintenance_flag = 0
        if  pwr < 0.0:
            pwr = 0
            count_pwr = count_pwr + 1
            temp = oldtemp
        elif 0 < count_pwr < NB_RECORDS_IMPACTED:
            # When the power is off the temperature increases
            count_pwr = count_pwr + 1
            pwr = 0
            temp = oldtemp + 0.8 * count_pwr
        if count_pwr == NB_RECORDS_IMPACTED:
            # when it reaches n records at power 0 time to flag it
            maintenance_flag = 1
            count_pwr = 0
            pwrc = 0

        new_temp[i] = temp
        new_maint_req[i] = maintenance_flag
        new_power[i] = pwr
        new_power_consumption[i] = pwrc

    return {
        "Temperature(celsius)": new_temp, 
        "Maintenance_Required": new_maint_req, 
        "Power": new_power,
        "PowerConsumption": new_power_consumption
    }


class ReeferSimulator:
    # Constants used elsewhere in the application
    SIMUL_POWEROFF="poweroff"
    SIMUL_CO2="co2sensor"

    # Order of columns in returned dataframes
    COLUMN_ORDER = ["Timestamp", "ID", "Temperature(celsius)", 
                    "Target_Temperature(celsius)", "Power", "PowerConsumption", 
                    "ContentType", "O2", "CO2", "Time_Door_Open", 
                    "Maintenance_Required", "Defrost_Cycle"]

    def generatePowerOff(self,
                         cid: str = "101", 
                         nb_records: int = MAX_RECORDS, 
                         tgood: float = 4.4,
                         content_type: int = None,
                         start_time: datetime.datetime = None):
        '''
        Generate n records for training and test set for the power off 
        simulation.
        Power off will be off for NB_RECORDS_IMPACTED events.

        Arguments:
            cid: Container ID
            nb_records: Number of records to generate
            tgood: Mean temperature to generate when power is NOT off
            content_type: ID of the type of stuff in the container, or None
                to choose a random number
            start_time: Timestamp of first row, or None to use the current time.
                By convention, each subsequent row will be exactly 15 minutes 
                later.

        Returns a Pandas dataframe.
        '''
        #print("Generating ",nb_records, " poweroff metrics")

        df = _generateStationaryCols(nb_records, cid, content_type, tgood)
        df["Timestamp"] = _generateTimestamps(nb_records, start_time)

        # Run a state machine to simulate the power-off events.
        state_machine_results = _simulatePowerOff(nb_records, tgood) 
        for col_name in ("Temperature(celsius)", 
                         "Maintenance_Required", 
                         "Power", "PowerConsumption"):
            df[col_name] = state_machine_results[col_name]

        return df[ReeferSimulator.COLUMN_ORDER]

    def generatePowerOffTuples(self,
                               cid: str = "101",
                               nb_records: int = MAX_RECORDS,
                               tgood: float = 4.4,
                               content_type: int = None,
                               start_time: datetime.datetime = None):
        '''
        Generate an array of tuples with reefer container values

        Arguments:
            cid: Container ID
            nb_records: Number of records to generate
            tgood: Mean temperature to generate when power is NOT off
            content_type: ID of the type of stuff in the container, or None
                to choose a random number
            start_time: Timestamp of first row, or None to use the current time.
                By convention, each subsequent row will be exactly 15 minutes 
                later.

        Returns an array of Python tuples, where the order of fields in the tuples
        the same as that in ReeferSimulator.COLUMN_ORDER.
        '''
        df = generatePowerOff(cid, nb_records, tgood, content_type)

        # Original code always generated 0 for the "maintenance required" field
        # when generating tuples.
        df["Maintenance_Required"] = np.repeat(0, nb_records)

        # Original code returned a Python list of Python tuples, so we strip the
        # schema information out of the Numpy record array returned by
        # DataFrame.to_records().
        return list(df.to_records(index=False))

    def generateCo2(self,
                    cid: str = "101", 
                    nb_records: int = MAX_RECORDS, 
                    tgood: float = 4.4,
                    content_type: int = None,
                    start_time: datetime.datetime = None):
        '''
        Generate a dataframe of training data for CO2 sensor malfunctions.

        Arguments:
            cid: Container ID
            nb_records: Number of records to generate
            tgood: Mean temperature to generate when power is NOT off
            content_type: ID of the type of stuff in the container, or None
                to choose a random number
            start_time: Timestamp of first row, or None to use the current time.
                By convention, each subsequent row will be exactly 15 minutes 
                later.

        Returns a Pandas dataframe with the schema given in 
        ReeferSimulator.COLUMN_ORDER.
        '''
        df = _generateStationaryCols(nb_records, cid, content_type, tgood)
        df["Timestamp"] = _generateTimestamps(nb_records, start_time)
        df["PowerConsumption"] = df["Power"].cumsum()
        df["Maintenance_Required"] = ((df["CO2"] > CO2_LEVEL) 
                                      | (df["CO2"] < 0)).astype(np.int)
        return df[ReeferSimulator.COLUMN_ORDER]


    def generateCo2Tuples(self,
                    cid: str = "101", 
                    nb_records: int = MAX_RECORDS, 
                    tgood: float = 4.4,
                    content_type: int = None,
                    start_time: datetime.datetime = None):
        '''
        Generate a dataframe of training data for CO2 sensor malfunctions.

        Arguments:
            cid: Container ID
            nb_records: Number of records to generate
            tgood: Mean temperature to generate when power is NOT off
            content_type: ID of the type of stuff in the container, or None
                to choose a random number
            start_time: Timestamp of first row, or None to use the current time.
                By convention, each subsequent row will be exactly 15 minutes 
                later.

        Returns an array of Python tuples, where the order of fields in the tuples
        the same as that in ReeferSimulator.COLUMN_ORDER.
        '''
        df = generateCo2(cid, nb_records, tgood, content_type, start_time)

        # Original code always generated 0 for the "maintenance required" field
        # when generating tuples.
        df["Maintenance_Required"] = np.repeat(0, nb_records)

        # Original code returned a Python list of Python tuples, so we strip the
        # schema information out of the Numpy record array returned by
        # DataFrame.to_records().
        return list(df.to_records(index=False))

