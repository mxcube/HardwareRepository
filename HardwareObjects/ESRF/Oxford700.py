from HardwareRepository.BaseHardwareObjects import HardwareObject
from HardwareRepository import HardwareRepository as HWR
import gevent
import sys

CRYO_STATUS = ["OFF", "SATURATED", "READY", "WARNING", "FROZEN", "UNKNOWN"]
PHASE_ACTION = {
    "RAMP": "ramp",
    "COOL": "cool",
    "HOLD": "hold",
    "PLAT": "plat",
    "PURGE": "purge",
    "END": "end",
}


class Oxford700(HardwareObject):
    def __init__(self, name):
        HardwareObject.__init__(self, name)

        self.temp = None
        self.temp_error = None

    def _do_polling(self):
        while True:
            try:
                self.value_changed()
            except Exception:
                sys.excepthook(*sys.exc_info())
            gevent.sleep(self.interval)

    def init(self):
        controller = HWR.get_hardware_repository().get_hardware_object(
            self.get_property("controller")
        )
        cryostat = self.get_property("cryostat")
        self.interval = self.get_property("interval") or 10
        self.ctrl = getattr(controller, cryostat)
        if self.ctrl is not None:
            # self.get_params()
            gevent.spawn(self._do_polling)
            self._hw_ctrl = self.ctrl.controller._hw_controller

    def value_changed(self):
        self.emit("temperatureChanged", (self.get_temperature(),))
        self.emit("valueChanged", (self.get_temperature(),))
        self.emit("stateChanged", (self.get_state(),))

    def get_temperature(self):
        return self.ctrl.input.read()

    def get_value(self):
        return self.get_temperature()

    def rampstate(self):
        return self.ctrl.is_ramping()

    def start_action(self, phase="RAMP", target=None, rate=None):
        if phase in PHASE_ACTION:
            action = getattr(self._hw_ctrl, PHASE_ACTION[phase])
            if rate:
                action(target, rate=rate)
            elif target:
                action(target)
            else:
                action()

    def stop_action(self, phase="HOLD"):
        if phase in PHASE_ACTION:
            getattr(self._hw_ctrl, PHASE_ACTION[phase])

    def pause(self, execute=True):
        if execute:
            self._hw_ctrl.pause()
        else:
            self._hw_ctrl.resume()

    def get_state(self):
        try:
            return self._hw_ctrl.read_run_mode().upper()
        except (AttributeError, TypeError):
            return "UNKNOWN"

    def get_static_parameters(self):
        return ["oxford", "K", "hour"]

    def get_params(self):
        run_mode = self._hw_ctrl.read_run_mode()
        target = self.ctrl.setpoint
        rate = self.ctrl.ramprate
        phase = self._hw_ctrl.read_phase()
        self.temp = self.ctrl.input.read()
        return [target, rate, phase.upper(), run_mode]
