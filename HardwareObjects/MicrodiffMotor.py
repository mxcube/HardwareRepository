import time
from gevent import Timeout
from HardwareRepository.HardwareObjects.abstract.AbstractMotor import AbstractMotor


class MD2TimeoutError(Exception):
    pass


"""
Example xml file:
<device class="MicrodiffMotor">
  <username>phiy</username>
  <exporter_address>wid30bmd2s:9001</exporter_address>
  <motor_name>AlignmentY</motor_name>
  <GUIstep>1.0</GUIstep>
  <unit>-1e-3</unit>
  <resolution>1e-2</resolution>
</device>
"""


class MicrodiffMotor(AbstractMotor):
    (NOTINITIALIZED, UNUSABLE, READY, MOVESTARTED, MOVING, ONLIMIT) = (0, 1, 2, 3, 4, 5)
    EXPORTER_TO_MOTOR_STATE = {
        "Invalid": NOTINITIALIZED,
        "Fault": UNUSABLE,
        "Ready": READY,
        "Moving": MOVING,
        "Created": NOTINITIALIZED,
        "Initializing": NOTINITIALIZED,
        "Unknown": UNUSABLE,
        "Offline": UNUSABLE,
        "LowLim": ONLIMIT,
        "HighLim": ONLIMIT,
    }

    TANGO_TO_MOTOR_STATE = {"STANDBY": READY, "MOVING": MOVING}

    def __init__(self, name):
        AbstractMotor.__init__(self, name)
        self.motor_pos_attr_suffix = "Position"
        self.motor_state_attr_suffix = "State"
        self.translate_state = {
            MicrodiffMotor.NOTINITIALIZED: self.motor_states.NOTINITIALIZED,
            MicrodiffMotor.UNUSABLE: self.motor_states.BUSY,
            MicrodiffMotor.READY: self.motor_states.READY,
            MicrodiffMotor.MOVESTARTED: self.motor_states.MOVESTARTED,
            MicrodiffMotor.MOVING: self.motor_states.MOVING,
            MicrodiffMotor.ONLIMIT: self.motor_states.HIGHLIMIT,
        }

    def init(self):
        self.position = None
        # assign value to motor_name
        self.motor_name = self.getProperty("motor_name")

        self.GUIstep = self.getProperty("GUIstep")

        self.motor_resolution = self.getProperty("resolution")
        if self.motor_resolution is None:
            self.motor_resolution = 0.0001

        # this is ugly : I added it to make the centring procedure happy
        self.specName = self.motor_name

        self.motorState = MicrodiffMotor.NOTINITIALIZED

        self.position_attr = self.getChannelObject(
            "%s%s" % (self.motor_name, self.motor_pos_attr_suffix)
        )
        if not self.position_attr:
            self.position_attr = self.addChannel(
                {"type": "exporter", "name": "%sPosition" % self.motor_name},
                self.motor_name + self.motor_pos_attr_suffix,
            )

        if self.position_attr is not None:
            self.state_attr = self.getChannelObject(
                "%s%s" % (self.motor_name, self.motor_state_attr_suffix)
            )
            if not self.state_attr:
                self.state_attr = self.addChannel(
                    {"type": "exporter", "name": "%sState" % self.motor_name},
                    self.motor_name + self.motor_state_attr_suffix,
                )

            self.position_attr.connectSignal("update", self.motorPositionChanged)
            self.state_attr.connectSignal("update", self.motorStateChanged)

            self.motors_state_attr = self.getChannelObject("motor_states")
            if not self.motors_state_attr:
                self.motors_state_attr = self.addChannel(
                    {"type": "exporter", "name": "motor_states"}, "MotorStates"
                )
            self.motors_state_attr.connectSignal("update", self.updateMotorState)

            self._motor_abort = self.getCommandObject("abort")
            if not self._motor_abort:
                self._motor_abort = self.addCommand(
                    {"type": "exporter", "name": "abort"}, "abort"
                )

            self.get_dynamic_limits_cmd = self.getCommandObject(
                "get%sDynamicLimits" % self.motor_name
            )
            if not self.get_dynamic_limits_cmd:
                self.get_dynamic_limits_cmd = self.addCommand(
                    {
                        "type": "exporter",
                        "name": "get%sDynamicLimits" % self.motor_name,
                    },
                    "getMotorDynamicLimits",
                )

            self.get_limits_cmd = self.getCommandObject("getMotorLimits")
            if not self.get_limits_cmd:
                self.get_limits_cmd = self.addCommand(
                    {"type": "exporter", "name": "get_limits"}, "getMotorLimits"
                )

            self.get_max_speed_cmd = self.getCommandObject("getMotorMaxSpeed")
            if not self.get_max_speed_cmd:
                self.get_max_speed_cmd = self.addCommand(
                    {"type": "exporter", "name": "get_max_speed"}, "getMotorMaxSpeed"
                )

            self.home_cmd = self.getCommandObject("homing")
            if not self.home_cmd:
                self.home_cmd = self.addCommand(
                    {"type": "exporter", "name": "homing"}, "startHomingMotor"
                )

        self.motorPositionChanged(self.position_attr.getValue())

    def connectNotify(self, signal):
        if signal == "positionChanged":
            self.emit("positionChanged", (self.get_position(),))
        elif signal == "stateChanged":
            self.motorStateChanged(self.state_attr.getValue())
        elif signal == "limitsChanged":
            self.motorLimitsChanged()

    def updateState(self):
        self.setIsReady(self._get_state() > MicrodiffMotor.UNUSABLE)

    def setIsReady(self, value):
        if value is True:
            self.set_ready()

    def updateMotorState(self, motor_states):
        d = dict([x.split("=") for x in motor_states])
        # Some are like motors but have no state
        # we set them to ready
        _motor_state = d.get(self.motor_name)
        if _motor_state is None:
            new_motor_state = MicrodiffMotor.READY
        else:
            if _motor_state in MicrodiffMotor.EXPORTER_TO_MOTOR_STATE:
                new_motor_state = MicrodiffMotor.EXPORTER_TO_MOTOR_STATE[_motor_state]
            else:
                new_motor_state = MicrodiffMotor.TANGO_TO_MOTOR_STATE[_motor_state]
        if self.motorState == new_motor_state:
            return
        self.motorState = new_motor_state
        self.motorStateChanged(self.motorState)

    def motorStateChanged(self, state):
        self.updateState()
        if not isinstance(state, int):
            state = self.get_state()
        self.emit("stateChanged", (state,))

    def _get_state(self):
        state_value = self.state_attr.getValue()
        if state_value in MicrodiffMotor.EXPORTER_TO_MOTOR_STATE:
            self.motorState = MicrodiffMotor.EXPORTER_TO_MOTOR_STATE[state_value]
        else:
            self.motorState = MicrodiffMotor.TANGO_TO_MOTOR_STATE[state_value.name]
        return self.motorState

    def get_state(self):
        state = self._get_state()
        return self.translate_state[state]

    def motorLimitsChanged(self):
        self.emit("limitsChanged", (self.get_limits(),))

    def get_limits(self):
        dynamic_limits = self.getDynamicLimits()
        if dynamic_limits != (-1e4, 1e4):
            return dynamic_limits
        else:
            try:
                low_lim, hi_lim = map(float, self.get_limits_cmd(self.motor_name))
                if low_lim == float(1e999) or hi_lim == float(1e999):
                    raise ValueError
                return low_lim, hi_lim
            except BaseException:
                return (-1e4, 1e4)

    def getDynamicLimits(self):
        try:
            low_lim, hi_lim = map(float, self.get_dynamic_limits_cmd(self.motor_name))
            if low_lim == float(1e999) or hi_lim == float(1e999):
                raise ValueError
            return low_lim, hi_lim
        except BaseException:
            return (-1e4, 1e4)

    def getMaxSpeed(self):
        return self.get_max_speed_cmd(self.motor_name)

    def motorPositionChanged(self, absolute_position, private={}):
        if None not in (absolute_position, self.position):
            if abs(absolute_position - self.position) <= self.motor_resolution:
                return
        self.position = absolute_position
        self.emit("positionChanged", (self.position,))

    def get_position(self):
        if self.position_attr is not None:
            self.position = self.position_attr.getValue()
        return self.position

    def getDialPosition(self):
        return self.get_position()

    def move(self, absolutePosition, wait=True, timeout=None):
        # if self.get_state() != MicrodiffMotor.NOTINITIALIZED:
        if abs(self.position - absolutePosition) >= self.motor_resolution:
            self.position_attr.setValue(
                absolutePosition
            )  # absolutePosition-self.offset)

    def moveRelative(self, relativePosition):
        self.move(self.get_position() + relativePosition)

    def syncMoveRelative(self, relative_position, timeout=None):
        return self.syncMove(self.get_position() + relative_position)

    def waitEndOfMove(self, timeout=None):
        with Timeout(timeout):
            time.sleep(0.1)
            while self.motorState == MicrodiffMotor.MOVING:
                time.sleep(0.1)

    def syncMove(self, position, timeout=None):
        self.move(position)
        try:
            self.waitEndOfMove(timeout)
        except BaseException:
            raise MD2TimeoutError

    def motorIsMoving(self):
        return self.isReady() and self.motorState == MicrodiffMotor.MOVING

    def getMotorMnemonic(self):
        return self.motor_name

    def stop(self):
        if self.get_state() != MicrodiffMotor.NOTINITIALIZED:
            self._motor_abort()

    def homeMotor(self, timeout=None):
        self.home_cmd(self.motor_name)
        try:
            self.waitEndOfMove(timeout)
        except BaseException:
            raise MD2TimeoutError
