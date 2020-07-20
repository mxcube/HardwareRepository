#
#  Project: MXCuBE
#  https://github.com/mxcube
#
#  This file is part of MXCuBE software.
#
#  MXCuBE is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Lesser General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  MXCuBE is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with MXCuBE. If not, see <http://www.gnu.org/licenses/>.

"""
[Name] EMBLMachineInfo

[Description]
Hardware Object is used to get relevant machine information
(current, intensity, hutch temperature and humidity, and data storage disc
information). Value limits are included
"""
import os
import time
import logging

try:
    from urllib2 import urlopen
except ImportError:
    from urllib.request import urlopen

from datetime import datetime, timedelta
from gevent import spawn

from HardwareRepository.BaseHardwareObjects import HardwareObject


__credits__ = ["EMBL Hamburg"]
__license__ = "LGPLv3+"
__category__ = "General"


class EMBLMachineInfo(HardwareObject):
    """Displays actual information about the beeamline
    """

    def __init__(self, name):

        HardwareObject.__init__(self, name)

        self.update_interval = None
        self.limits_dict = None
        self.hutch_temp_addr = None
        self.hutch_hum_addr = None
        self.hutch_temp = 0
        self.hutch_hum = 0
        self.overflow_alarm = None
        self.low_level_alarm = None
        self.state_text = ""
        self.ring_energy = None
        self.bunch_count = None
        self.flux_area = None
        self.last_transmission = None
        self.frontend_is_open = False
        self.undulator_gap = 9999

        self.values_list = []

        temp_dict = {}
        temp_dict["value"] = 0
        temp_dict["value_str"] = ""
        temp_dict["in_range"] = False
        temp_dict["title"] = "Machine current"
        temp_dict["bold"] = True
        # temp_dict['font'] = 16
        # temp_dict['history'] = True
        self.values_list.append(temp_dict)

        temp_dict = {}
        temp_dict["value"] = None
        temp_dict["in_range"] = True
        temp_dict["title"] = "Machine state"
        self.values_list.append(temp_dict)

        temp_dict = {}
        temp_dict["value"] = None
        temp_dict["in_range"] = True
        temp_dict["title"] = "Front End, undulator gap"
        self.values_list.append(temp_dict)

        temp_dict = {}
        temp_dict["value"] = ""
        temp_dict["value_str"] = ""
        temp_dict["in_range"] = None
        temp_dict["title"] = "Hutch temperature and humidity"
        self.values_list.append(temp_dict)

        temp_dict = {}
        temp_dict["value"] = 1
        temp_dict["value_str"] = "Remeasure flux!"
        temp_dict["in_range"] = False
        temp_dict["title"] = "Measured / Estimated flux"
        temp_dict['align'] = "left"
        self.values_list.append(temp_dict)

        temp_dict = {}
        temp_dict["value"] = "???"
        temp_dict["in_range"] = None
        temp_dict["title"] = "Cryoject in place"
        self.values_list.append(temp_dict)

        temp_dict = {}
        temp_dict["value"] = "Dewar level in range"
        temp_dict["in_range"] = True
        temp_dict["title"] = "Sample changer"
        self.values_list.append(temp_dict)

        self.temp_hum_values = [None, None]
        self.temp_hum_in_range = [None, None]
        self.temp_hum_polling = None

        self.chan_mach_curr = None
        self.chan_mach_energy = None
        self.chan_bunch_count = None
        self.chan_frontend_status = None
        self.chan_undulator_gap = None
        self.chan_state_text = None
        self.chan_cryojet_in = None
        self.chan_cryojet_temperature = None
        self.chan_sc_dewar_low_level_alarm = None
        self.chan_sc_dewar_overflow_alarm = None

        self.cryojet_temperature = "Unknown"

        self.flux_hwobj = None
        self.ppu_control_hwobj = None

        self.frames_collected = 0
        self.frames_processed = 0
        self.frames_dropped = 0
        self.framse_average_i = 0

    def init(self):

        self.update_interval = int(self.getProperty("updateIntervalS"))
        self.limits_dict = eval(self.getProperty("limits"))
        self.hutch_temp_addr = self.getProperty("hutchTempAddress")
        self.hutch_hum_addr = self.getProperty("hutchHumAddress")

        self.chan_mach_curr = self.getChannelObject("machCurrent")
        if self.chan_mach_curr is not None:
            self.chan_mach_curr.connectSignal("update", self.mach_current_changed)
        self.chan_state_text = self.getChannelObject("machStateText")
        if self.chan_state_text is not None:
            self.chan_state_text.connectSignal("update", self.state_text_changed)
            self.state_text_changed(self.chan_state_text.getValue())

        self.chan_mach_energy = self.getChannelObject("machEnergy")
        if self.chan_mach_energy is not None:
            self.chan_mach_energy.connectSignal("update", self.mach_energy_changed)
        self.chan_bunch_count = self.getChannelObject("machBunchCount")
        if self.chan_bunch_count is not None:
            self.chan_bunch_count.connectSignal("update", self.bunch_count_changed)
        self.chan_frontend_status = self.getChannelObject("frontEndStatus")
        if self.chan_frontend_status is not None:
            self.chan_frontend_status.connectSignal(
                "update", self.frontend_status_changed
            )
            self.frontend_status_changed(self.chan_frontend_status.getValue())

        self.chan_undulator_gap = self.getChannelObject("chanUndulatorGap")
        if self.chan_undulator_gap is not None:
            self.chan_undulator_gap.connectSignal("update", self.undulator_gap_changed)
            self.undulator_gap_changed(self.chan_undulator_gap.getValue())

        self.chan_cryojet_in = self.getChannelObject("cryojetIn")
        if self.chan_cryojet_in is not None:
            self.cryojet_in_changed(self.chan_cryojet_in.getValue())
            self.chan_cryojet_in.connectSignal("update", self.cryojet_in_changed)
        else:
            logging.getLogger("HWR").debug("MachineInfo: Cryojet channel not defined")

        self.chan_cryojet_temperature = self.getChannelObject("cryojetTemperature")
        if self.chan_cryojet_temperature is not None:
            self.cryojet_temperature_changed(self.chan_cryojet_temperature.getValue())
            self.chan_cryojet_temperature.connectSignal("update", self.cryojet_temperature_changed)
        else:
            logging.getLogger("HWR").debug("MachineInfo: Cryojet temperature channel not defined")


        self.chan_sc_dewar_low_level_alarm = self.getChannelObject("scLowLevelAlarm")
        if self.chan_sc_dewar_low_level_alarm is not None:
            self.chan_sc_dewar_low_level_alarm.connectSignal(
                "update", self.low_level_alarm_changed
            )
            self.low_level_alarm_changed(self.chan_sc_dewar_low_level_alarm.getValue())

        self.chan_sc_dewar_overflow_alarm = self.getChannelObject("scOverflowAlarm")
        if self.chan_sc_dewar_overflow_alarm is not None:
            self.chan_sc_dewar_overflow_alarm.connectSignal(
                "update", self.overflow_alarm_changed
            )

        self.ppu_control_hwobj = self.getObjectByRole("ppu_control")
        if self.ppu_control_hwobj is not None:
            temp_dict = {}
            temp_dict["value"] = "- - -"
            temp_dict["in_range"] = False
            temp_dict["title"] = "Files copied - pending - failed"
            self.values_list.append(temp_dict)

            self.connect(
                self.ppu_control_hwobj,
                "fileTranferStatusChanged",
                self.file_transfer_status_changed,
            )

        self.chan_count_dropped = self.getChannelObject("framesCountDropped")
        if self.chan_count_dropped is not None:
            temp_dict = {}
            temp_dict["value"] = ""
            temp_dict["in_range"] = True
            temp_dict["title"] = "Frames dropped"
            self.values_list.append(temp_dict)
 
            self.chan_count_dropped.connectSignal(
                "update", self.count_dropped_changed
            )
        """
        self.chan_average_i = self.getChannelObject("framesAverageI")
        if self.chan_average_i is not None:
            self.chan_average_i.connectSignal(
                "update", self.frames_average_i_changed
            )
        """

        self.flux_hwobj = self.getObjectByRole("flux")
        self.connect(self.flux_hwobj, "fluxInfoChanged", self.flux_info_changed)
        self.temp_hum_polling = spawn(
            self.get_temp_hum_values, self.getProperty("updateIntervalS")
        )

        self.update_values()

    def clear_gevent(self):
        """Clear gevent tasks

        :return: None
        """
        self.temp_hum_polling.kill()
        if self.update_task:
            self.update_task.kill()

    def cryojet_temperature_changed(self, value):
        self.cryojet_temperature = value
        self.values_list[5]["value"] = "%s Temp: %s K"%(self.values_list[5]["value"].split(" Temp:")[0],value)
        if value < 111. and self.values_list[5]["in_range"]:
           self.values_list[5]["in_range"] = True
        else:
           self.values_list[5]["in_range"] = False

        self.update_values()

    def cryojet_in_changed(self, value):
        """Updates cryojet status
 
        :param value: status
        :type value: bool
        :return: None
        """

        self.values_list[5]["in_range"] = False
        self.values_list[5]["bold"] = True and ( self.cryojet_temperature < 111. )

        if value == 1:
            self.values_list[5]["value"] = " In place Temp: %s K" %self.cryojet_temperature
            self.values_list[5]["in_range"] = True and ( self.cryojet_temperature < 111. )
            self.values_list[5]["bold"] = False
        elif value == 0:
            self.values_list[5]["value"] = "NOT IN PLACE Temp: %s K"  %self.cryojet_temperature
        else:
            self.values_list[5]["value"] = "Unknown"
        
        self.update_values()


    def mach_current_changed(self, value):
        """Method called if the machine current is changed

        :param value: new machine current
        :type value: float
        """
        if (
            self.values_list[0]["value"] is None
            or abs(self.values_list[0]["value"] - value) > 0.00001
        ):
            self.values_list[0]["value"] = value
            self.values_list[0]["value_str"] = "%.1f mA" % value
            self.values_list[0]["in_range"] = value > 60.0
            self.update_values()

    def state_text_changed(self, text):
        """Function called if machine state text is changed

        :param text: new machine state text
        :type text: string
        """
        self.state_text = str(text)
        self.values_list[1]["in_range"] = text != "Fehler"
        self.update_machine_state()

    def mach_energy_changed(self, value):
        """Updates machine energy value

        :param value: machine energy
        :type value: float
        :return: None
        """
        self.ring_energy = value
        self.update_machine_state()

    def bunch_count_changed(self, value):
        """Bunch count changed"""
        self.bunch_count = value
        self.update_machine_state()

    def frontend_status_changed(self, value):
        """
        Update front end status
        :param value:
        :return:
        """
        if value:
            self.frontend_is_open = value[2] == 2
            self.update_machine_state()

    def undulator_gap_changed(self, value):
        """
        Update undulator gaps
        :param value: float
        :return:
        """
        if isinstance(value, (list, tuple)):
            value = value[0]
        self.undulator_gap = value / 1000

    def update_machine_state(self):
        """Machine state assembly"""
        state_text = self.state_text
        if self.ring_energy is not None:
            state_text += "\n%.2f GeV " % self.ring_energy
        if self.bunch_count is not None:
            state_text += ", %d Bunches" % self.bunch_count
        self.values_list[1]["value"] = state_text

        if not self.frontend_is_open or self.undulator_gap > 30:
            self.values_list[2]["in_range"] = False
        else:
            self.values_list[2]["in_range"] = True
        if self.frontend_is_open:
            self.values_list[2]["value_str"] = "Opened, %5.2f mm" % self.undulator_gap
        else:
            self.values_list[2]["value_str"] = "Closed, %5.2f mm" % self.undulator_gap

        self.update_values()

    def low_level_alarm_changed(self, value):
        """Low level alarm"""
        self.low_level_alarm = value
        self.update_sc_alarm()

    def overflow_alarm_changed(self, value):
        """Overflow alarm"""
        self.overflow_alarm = value
        self.update_sc_alarm()

    def file_transfer_status_changed(self, status):
        """
        Updates info about file beeing transfered
        :param total: int
        :param pending: int
        :param failed: int
        :return:
        """
        self.values_list[-1]["value"] = "%d  -  %d  -  %d" % \
            (status[0], status[1], status[2])
        self.values_list[-1]["in_range"] = status[2] == 0

        if status[2] > 0:
            logging.getLogger("GUI").error(
                "Error in file transfer (%d files failed to copy)." % status[2]
            )

    def count_dropped_changed(self, num_frames_dropped):
        self.frames_dropped = num_frames_dropped
        self.update_frame_info()

    def frames_average_i_changed(self, average_i):
        self.frames_average_i = average_i
        self.update_frame_info()

    def set_frames_collected(self, num_frames_collected):
        self.frames_collected = num_frames_collected
        self.update_frame_info()

    def update_frame_info(self):
        #self.values_list[-1]["value"] = "collected / processed / average-i / dropped \n"
        #self.values_list[-1]["value"] += " %d / %d / %.3f / %d" % (
        #     self.frames_collected, self.frames_processed, self.frames_average_i, self.frames_dropped
        #)
        self.values_list[-1]["value"] = str(self.frames_dropped)
        self.values_list[-1]["in_range"] = self.frames_dropped == 0

        if self.frames_dropped > 0:
            logging.getLogger("GUI").error(
                "Error in file transfer (%d files droped)." % self.frames_dropped
            )
        self.update_values()

    def update_sc_alarm(self):
        """Sample changer alarm"""
        if self.low_level_alarm == 1:
            self.values_list[6]["value"] = "Low level alarm!"
            self.values_list[6]["in_range"] = False
            self.values_list[6]["bold"] = True
            logging.getLogger("GUI").error(
                "Liquid nitrogen level in sample changer dewar is too low!"
            )

        elif self.overflow_alarm:
            self.values_list[6]["value"] = "Overflow alarm!"
            self.values_list[6]["in_range"] = False
            self.values_list[6]["bold"] = True
            logging.getLogger("GUI").error(
                "Liquid nitrogen overflow in sample changer dewar!"
            )
        else:
            self.values_list[6]["value"] = "Dewar level in range"
            self.values_list[6]["in_range"] = True
        self.update_values()

    def flux_info_changed(self, flux_info):
        """Sets flux value"""

        if flux_info["measured"] is None:
            self.values_list[4]["value"] = 0
            self.values_list[4]["value_str"] = "Beamline mode changed\nRemeasure flux!"
            self.values_list[4]["in_range"] = False
        else:
            msg_str = "Flux                  : %.2E ph/s  /  %.2E ph/s \n" % (flux_info["measured"]["flux"],
                                             flux_info["current"]["flux"])
            msg_str += "Transmission : %d%%  /  %4.1f%%\n" % (flux_info["measured"]["transmission"],
                                                      flux_info["current"]["transmission"])

            msg_str += "Beam size       : %dx%d  /  %dx%d" % (
                flux_info["measured"]["size_x"] * 1000,
                flux_info["measured"]["size_y"] * 1000,
                flux_info["current"]["size_x"] * 1000,
                flux_info["current"]["size_y"] * 1000
            )

            self.values_list[4]["value"] = flux_info["measured"]["flux"]
            self.values_list[4]["value_str"] = msg_str
            self.values_list[4]["in_range"] = flux_info["measured"]["flux"] > 1e6
        self.update_values()

    def flux_value_changed(self, flux_value):
        """
        Updates flux value
        :param flux_value:
        :return:
        """
        self.values_list[4]["value"] = flux_value
        self.values_list[4]["value_str"] = "%.2E ph/s" % flux_value
        self.values_list[4]["in_range"] = flux_value > 1e6
        self.update_values()

    def update_values(self):
        """Emits list of values"""
        self.emit("valuesChanged", self.values_list)

    def get_values(self):
        """Returns list of values"""
        return self.values_list

    def get_temp_hum_values(self, sleep_time):
        """Updates temperatur and humidity values"""
        while True:
            temp = self.get_external_value(self.hutch_temp_addr)
            hum = self.get_external_value(self.hutch_hum_addr)
            if not None in (temp, hum):
                if abs(float(temp) - self.hutch_temp) > 0.1 or abs(
                    float(hum) != self.hutch_hum > 1
                ):
                    self.hutch_temp = temp
                    self.hutch_hum = hum
                    self.values_list[3]["value"] = "%.1f C, %.1f %%" % (temp, hum)
                    self.values_list[3]["in_range"] = temp < 25 and hum < 60
                    self.update_values()
            time.sleep(sleep_time)

    def get_current(self):
        """Returns machine current in mA
        """
        return self.values_list[0]["value"]

    def get_current_value(self):
        """Returns machine current in mA"""
        return self.values_list[0]["value"]

    def get_message(self):
        """Returns synchrotron state text"""
        return self.state_text

    def get_external_value(self, addr):
        """Extracts value from the given epics address. This is very specific
           implementation how to get a value from epics web tool. At first
           web address string is formed and then web page by urllib2
           extracted. Page contains column with records.
           Then the last value is choosen as the last active value.

        :param addr: epics address
        :type addr: str
        :returns : float
        """
        url_prefix = (
            "http://cssweb.desy.de:8084/ArchiveViewer/archive"
            + "reader.jsp?DIRECTORY=%2Fdata7%2FChannelArchiver%"
            + "2FchannelReference2.kryo&PATTERN=&"
        )
        end = datetime.now()
        start = end - timedelta(hours=24)
        url_date = "=on&STARTMONTH=%d&STARTDAY=%d&STARTYEAR=%d" % (
            start.month,
            start.day,
            start.year,
        ) + "&STARTHOUR=%d&STARTMINUTE=%d&STARTSECOND=0" % (start.hour, start.minute)
        url_date = url_date + (
            "&ENDMONTH=%d&ENDDAY=%d&ENDYEAR=%d" % (end.month, end.day, end.year)
            + "&ENDHOUR=%d&ENDMINUTE=%d&ENDSECOND=0" % (end.hour, (end.minute - 10))
        )
        url_date = (
            url_date
            + "&COMMAND=GET&Y0=0&Y1=0&FORMAT=SPREADSHEET&"
            + "INTERPOL=0&NUMOFPOINTS=10"
        )
        url_file = None
        last_value = None
        try:
            addr = addr.split(":")
            url_device = (
                "NAMES=" + addr[0] + "%3A" + addr[1] + "%3A" + addr[2] + "%3A" + addr[3]
            )
            url_device = (
                url_device
                + "&FRAME2=1"
                + addr[0]
                + "%3A"
                + addr[1]
                + "%3A"
                + addr[2]
                + "%3A"
                + addr[3]
            )
            url_device = (
                url_device
                + "&NAMES2=&"
                + addr[0]
                + "%3A"
                + addr[1]
                + "%3A"
                + addr[2]
                + "%3A"
                + addr[3]
            )
            final_url = url_prefix + url_device + url_date
            url_file = urlopen(final_url)
            for line in url_file:
                line_el = line.split()
                if line_el:
                    if line_el[-1].isdigit:
                        last_value = line_el[-1]
            last_value = float(last_value)
        except BaseException:
            logging.getLogger("HWR").debug("MachineInfo: Unable to read epics values")
        finally:
            if url_file:
                url_file.close()
        return last_value

    def update_ramdisk_size(self, sleep_time):
        """
        In the loop updates information about ramdisk size.
        Method gets total and free disc space and in Gb and formats a readable string
        :param sleep_time: sec between update cycles
        :return:
        """
        while True:
            total, free, perc = self.get_ramdisk_size()
            if None in (total, free, perc):
                txt = " Unable to read ramdisk size!"
                self.values_list[-1]["in_range"] = False
            else:
                txt = " Total: %s\n Free:  %s (%s)" % (
                    self.sizeof_fmt(total),
                    self.sizeof_fmt(free),
                    "{0:.0%}".format(perc),
                )
                self.values_list[-1]["in_range"] = free / 2 ** 30 > 10
            self.values_list[-1]["value"] = txt
            self.update_values()
            time.sleep(sleep_time)

    def get_ramdisk_size(self):
        """
        Gets ramdisk size in bytes
        :return: total, free disc size in bytes and free disc in perc
        """
        data_dir = "/ramdisk/"
        # p = '/' + data_dir.split('/')[1]
        # data_dir = str(p)
        if os.path.exists(data_dir):
            st = os.statvfs(data_dir)

            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            perc = st.f_bavail / float(st.f_blocks)
            return total, free, perc
        else:
            return None, None, None

    def sizeof_fmt(self, num):
        """Returns disk space formated in string"""

        try:
            for x in ["bytes", "KB", "MB", "GB"]:
                if num < 1024.0:
                    return "%3.1f%s" % (num, x)
                num /= 1024.0
            return "%3.1f%s" % (num, "TB")
        except BaseException:
            return "???"
