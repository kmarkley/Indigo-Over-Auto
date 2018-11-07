#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# Copyright (c) 2016, Perceptive Automation, LLC. All rights reserved.
# http://www.indigodomo.com

import indigo
import threading
import Queue
import time
from ghpu import GitHubPluginUpdater

# Note the "indigo" module is automatically imported and made available inside
# our global name space by the host process.

################################################################################
# Globals

k_commonTrueStates = ['true', 'on', 'open', 'up', 'yes', 'active', 'locked', '1']

k_updateCheckHours = 24

################################################################################
class Plugin(indigo.PluginBase):

    #-------------------------------------------------------------------------------
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        self.updater = GitHubPluginUpdater(self)

    #-------------------------------------------------------------------------------
    # Start, Stop and Config changes
    #-------------------------------------------------------------------------------
    def startup(self):
        self.nextCheck = self.pluginPrefs.get('nextUpdateCheck',0)
        self.debug = self.pluginPrefs.get("showDebugInfo",False)
        if self.debug:
            self.logger.debug(u"Debug logging enabled")
        self.instance_dict = dict()

        indigo.devices.subscribeToChanges()
        indigo.variables.subscribeToChanges()
        indigo.insteon.subscribeToIncoming()
        indigo.zwave.subscribeToIncoming()

    #-------------------------------------------------------------------------------
    def shutdown(self):
        self.pluginPrefs['nextUpdateCheck'] = self.nextCheck
        self.pluginPrefs['showDebugInfo'] = self.debug

    #-------------------------------------------------------------------------------
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.debug = valuesDict.get('showDebugInfo',False)
            if self.debug:
                self.logger.debug(u"Debug logging enabled")

    #-------------------------------------------------------------------------------
    def runConcurrentThread(self):
        try:
            while True:
                loop_time = time.time()
                for instance in self.instance_dict.values():
                    instance.task(instance.tick, loop_time)
                if loop_time > self.nextCheck:
                    self.checkForUpdates()
                self.sleep(1)
        except self.StopThread:
            pass

    #-------------------------------------------------------------------------------
    # Device Methods
    #-------------------------------------------------------------------------------
    def deviceStartComm(self, dev):
        if dev.configured:
            if dev.deviceTypeId == 'OverAutoDevice':
                self.instance_dict[dev.id] = OverAutoDevice(dev, self.logger)
            elif dev.deviceTypeId == 'OverAutoAction':
                self.instance_dict[dev.id] = OverAutoAction(dev, self.logger)

    #-------------------------------------------------------------------------------
    def deviceStopComm(self, dev):
        if dev.id in self.instance_dict:
            self.instance_dict[dev.id].cancel()
            while self.instance_dict[dev.id].is_alive():
                time.sleep(0.1)
            del self.instance_dict[dev.id]

    #-------------------------------------------------------------------------------
    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        errorsDict = indigo.Dict()

        if valuesDict['auto_control_type'] == 'device':
            if not valuesDict['auto_device_id']:
                errorsDict['auto_device_id'] = "Required"
            if not valuesDict['auto_state_key']:
                errorsDict['auto_state_key'] = "Required"
        elif valuesDict['auto_control_type'] == 'variable':
            if not valuesDict['auto_variable_id']:
                errorsDict['auto_variable_id'] = "Required"

        if valuesDict['over_control_type'] == 'device':
            if not valuesDict['over_device_id']:
                errorsDict['over_device_id'] = "Required"
            if not valuesDict['auto_state_key']:
                errorsDict['over_state_key'] = "Required"
        elif valuesDict['over_control_type'] == 'variable':
            if not valuesDict['over_variable_id']:
                errorsDict['over_variable_id'] = "Required"
        elif valuesDict['over_control_type'] == 'insteon':
            if not valuesDict['over_insteon_id']:
                errorsDict['over_insteon_id'] = "Required"
            if not valuesDict['over_insteon_button']:
                errorsDict['over_insteon_button'] = "Required"
        elif valuesDict['over_control_type'] == 'zwave':
            if not valuesDict['over_zwave_address']:
                errorsDict['over_zwave_address'] = "Required"

        if valuesDict['on_logic'] == 'timer':
            if not validateTextFieldNumber(valuesDict['on_timer_cycles'], numType=float, zero=False, negative=False):
                errorsDict['on_timer_cycles'] = "Must be a positive number"

        if valuesDict['off_logic'] == 'timer':
            if not validateTextFieldNumber(valuesDict['off_timer_cycles'], numType=float, zero=False, negative=False):
                errorsDict['off_timer_cycles'] = "Must be a positive number"

        if len(errorsDict) > 0:
            self.logger.debug(u"validate device config error: \n{}".format(errorsDict))
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    #-------------------------------------------------------------------------------
    # Device Config callbacks
    #-------------------------------------------------------------------------------
    def getDeviceStates(self, filter=None, valuesDict=dict(), typeId='', targetId=0):
        dev_id = valuesDict.get(filter,0)
        return [(state, state) for state in indigo.devices[int(dev_id)].states] if dev_id else []

    #-------------------------------------------------------------------------------
    def getInsteonButtons(self, filter=None, valuesDict=dict(), typeId='', targetId=0):
        dev_id = valuesDict.get(filter,0)
        button_count = indigo.devices[int(dev_id)].buttonGroupCount if dev_id else 0
        return [(i,'Button {}'.format(i)) for i in range(1,button_count+1)]

    #-------------------------------------------------------------------------------
    def getActionGroups(self, filter=None, valuesDict=dict(), typeId='', targetId=0):
        return [(action.id, action.name) for action in indigo.actionGroups.iter()] + [(0,'-- None --')]

    #-------------------------------------------------------------------------------
    def dummyCallback(self, valuesDict=None, typeId='', targetId=0):
        pass

    #-------------------------------------------------------------------------------
    # action control
    #-------------------------------------------------------------------------------
    def actionControlDevice(self, action, dev):
        instance = self.instance_dict[dev.id]

        # TURN ON
        if action.deviceAction == indigo.kDeviceAction.TurnOn:
            instance.overrideAction(True)
        # TURN OFF
        elif action.deviceAction == indigo.kDeviceAction.TurnOff:
            instance.overrideAction(False)
        # TOGGLE
        elif action.deviceAction == indigo.kDeviceAction.Toggle:
            instance.overrideAction(not instance.on_state)
        # UNKNOWN
        else:
            self.logger.debug(u'"{}" {} request ignored'.format(dev.name, action.deviceAction))

    #-------------------------------------------------------------------------------
    def actionControlUniversal(self, action, dev):
        instance = self.instance_dict[dev.id]

        # STATUS REQUEST
        if action.deviceAction == indigo.kUniversalAction.RequestStatus:
            self.logger.info('"{}" status update'.format(dev.name))
            instance.requestStatus()
        # UNKNOWN
        else:
            self.logger.debug(u'"{}" {} request ignored'.format(dev.name, action.deviceAction))

    #-------------------------------------------------------------------------------
    # custom action callbacks
    #-------------------------------------------------------------------------------
    def cancelOverride(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.overrideAction(None)

    #-------------------------------------------------------------------------------
    # menu methods
    #-------------------------------------------------------------------------------
    def checkForUpdates(self):
        try:
            self.updater.checkForUpdate()
        except Exception as e:
            msg = u"Check for update error.  Next attempt in {} hours.".format(k_updateCheckHours)
            if self.debug:
                self.logger.exception(msg)
            else:
                self.logger.error(msg)
                self.logger.debug(e)
        self.nextCheck = time.time() + k_updateCheckHours*60*60

    #-------------------------------------------------------------------------------
    def updatePlugin(self):
        self.updater.update()

    #-------------------------------------------------------------------------------
    def forceUpdate(self):
        self.updater.update(currentVersion='0.0.0')

    #-------------------------------------------------------------------------------
    def toggleDebug(self):
        if self.debug:
            self.logger.debug(u"Debug logging disabled")
            self.debug = False
        else:
            self.debug = True
            self.logger.debug(u"Debug logging enabled")

    #-------------------------------------------------------------------------------
    # subscribed changes
    #-------------------------------------------------------------------------------
    def deviceUpdated(self, old_dev, new_dev):
        if new_dev.pluginId == self.pluginId:
            # device belongs to plugin
            indigo.PluginBase.deviceUpdated(self, old_dev, new_dev)

        for instance in self.instance_dict.values():
            instance.task(instance.deviceUpdated, old_dev, new_dev)

    #-------------------------------------------------------------------------------
    def variableUpdated(self, old_var, new_var):
        for instance in self.instance_dict.values():
            instance.task(instance.variableUpdated, old_var, new_var)

    #-------------------------------------------------------------------------------
    def insteonCommandReceived(self, cmd):
        for instance in self.instance_dict.values():
            instance.task(instance.insteonCommandReceived, cmd)

    #-------------------------------------------------------------------------------
    def zwaveCommandReceived(self, cmd):
        for instance in self.instance_dict.values():
            instance.task(instance.zwaveCommandReceived, cmd)

###############################################################################
# Classes
###############################################################################
class OverAutoDevice(threading.Thread):
    # class properties
    k_update_states = ['onOffState','mode','state','state_auto','state_over','on_override_end','off_override_end','override_remain_short']
    k_triple = {'true':True, 'false':False, 'none':None}
    k_insteon_commands = {'single':('on','off'),'double':('on to 100% (instant)','off (instant)'),'hold':('brighten','dim')}

    #-------------------------------------------------------------------------------
    def __init__(self, device, logger):
        super(OverAutoDevice, self).__init__()
        self.daemon     = True
        self.cancelled  = False
        self.queue      = Queue.Queue()

        self.logger = logger

        self.state_changed = False
        self.selfUpdated(device)
        self.props = device.pluginProps

        self.on_logic  = self.props.get('on_logic',  'timer')
        self.on_over_duration  = self.delta(self.props.get('on_timer_cycles',0),  self.props.get('on_timer_units','seconds') ) if self.on_logic == 'timer' else 0
        self.off_logic = self.props.get('off_logic', 'timer')
        self.off_over_duration = self.delta(self.props.get('off_timer_cycles',0), self.props.get('off_timer_units','seconds')) if self.off_logic == 'timer' else 0

        self.auto_type = self.props.get('auto_control_type','device')
        self.auto_reverse = self.props.get('auto_reverse', False)
        self.auto_device_id = None
        self.auto_state_key = None
        self.auto_var_id = None
        if self.auto_type == 'device':
            self.auto_device_id = int(self.props['auto_device_id'])
            self.auto_state_key = self.props['auto_state_key']
        elif self.auto_type == 'variable':
            self.auto_var_id = int(self.props['auto_variable_id'])

        self.over_type = self.props.get('over_control_type','device')
        self.over_reverse = self.props.get('over_reverse', False)
        self.over_device_id = None
        self.over_state_key = None
        self.over_var_id = None
        self.over_insteon_address = None
        self.over_insteon_button = None
        self.over_insteon_command = (None,None)
        self.over_zwave_address = None
        if self.over_type == 'device':
            self.over_device_id = int(self.props['over_device_id'])
            self.over_state_key = self.props['over_state_key']
        elif self.over_type == 'variable':
            self.over_var_id = int(self.props['over_variable_id'])
        elif self.over_type == 'insteon':
            self.over_insteon_address = indigo.devices[int(self.props['over_insteon_id'])].address
            self.over_insteon_button = int(self.props['over_insteon_button'])
            self.over_insteon_command = self.k_insteon_commands[self.props['over_insteon_command']]
        elif self.over_type == 'zwave':
            self.over_zwave_address = self.props['over_zwave_address']

        self.output_type = self.props.get('output_type','device')
        if self.output_type == 'device':
            self.output_device_ids = self.props.get('output_device_ids',[])
            self.speed_control_index = [0,int(self.props.get('speed_control_index',3))]
            self.dimmer_control_level = [0,int (self.props.get('dimmer_control_level',100))]
            self.relayControlFunction = [indigo.device.turnOff, indigo.device.turnOn]
        elif self.output_type == 'action':
            self.action_on  = int(self.props['action_on'])
            self.action_off = int(self.props['action_off'])

        if self.states['state_over'] == 0:
            self.state_over = None
        self.updateIndigo()

        self.start()
        self.requestStatus()

    #-------------------------------------------------------------------------------
    def run(self):
        self.logger.debug('"{}" thread started'.format(self.name))
        while not self.cancelled:
            try:
                func, args = self.queue.get(True,2)
                try:
                    func(*args)
                except NotImplementedError:
                    self.logger.error('"{}" task "{}" not implemented'.format(self.name,func.__name__))
                self.queue.task_done()
            except Queue.Empty:
                pass
            except Exception as e:
                self.logger.exception('"{}" thread error \n{}'.format(self.name, e))
            self.updateIndigo()
        else:
            self.logger.debug('"{}" thread cancelled'.format(self.name))

    #-------------------------------------------------------------------------------
    def task(self, func, *args):
        # self.queue.put((func, args))
        func(*args)
        self.updateIndigo()

    #-------------------------------------------------------------------------------
    def cancel(self):
        self.cancelled = True

    #-------------------------------------------------------------------------------
    def deviceUpdated(self, old_dev, new_dev):
        if new_dev.id == self.dev.id:
            self.selfUpdated(new_dev)
        elif new_dev.id == self.auto_device_id:
            if new_dev.states[self.auto_state_key] != old_dev.states[self.auto_state_key]:
                self.state_auto = self.getBoolValue(new_dev.states[self.auto_state_key], self.auto_reverse)
        elif new_dev.id == self.over_device_id:
            if new_dev.states[self.over_state_key] != old_dev.states[self.over_state_key]:
                self.state_over = self.getBoolValue(new_dev.states[self.over_state_key], self. over_reverse)

    #-------------------------------------------------------------------------------
    def variableUpdated(self, old_var, new_var):
        if new_var.id == self.auto_var_id:
            if new_var.value != old_var.value:
                self.state_auto = self.getBoolValue(new_var.value, self.auto_reverse)
        elif new_var.id == self.over_var_id:
            if new_var.value != old_var.value:
                self.state_over = self.getBoolValue(new_var.value, self.over_reverse)

    #-------------------------------------------------------------------------------
    def insteonCommandReceived(self, cmd):
        if (cmd.address == self.over_insteon_address) and (cmd.cmdScene == self.over_insteon_button):
            if cmd.cmdFunc == self.over_insteon_command[0]:
                self.state_over = True
            elif cmd.cmdFunc == self.over_insteon_command[1]:
                self.state_over = False

    #-------------------------------------------------------------------------------
    def zwaveCommandReceived(self, cmd):
        pass

    #-------------------------------------------------------------------------------
    def selfUpdated(self, new_dev):
        self.dev = new_dev
        self.states = new_dev.states

    #-------------------------------------------------------------------------------
    def requestStatus(self):
        if self.auto_type == 'device':
            dev = indigo.devices[self.auto_device_id]
            value = dev.states[self.auto_state_key]
        elif self.auto_type == 'variable':
            var = indigo.variables[self.auto_var_id]
            value = var.value
        self.state_auto = self.getBoolValue(value, self.auto_reverse)
        self.tick()
        self.updateIndigo()

    #-------------------------------------------------------------------------------
    def overrideAction(self, value):
        if value in self.k_triple.values():
            self.state_over = value
        elif value in self.k_triple.keys():
            self.state_over = self.k_triple[value]
        else:
            self.logger.error('"{}" can\'t set override to {}'.format(self.dev.name,value))

    #-------------------------------------------------------------------------------
    def tick(self, tick_time=None):
        if tick_time is None:
            tick_time = time.time()
        if (self.state_over is True) and (self.on_logic == 'timer'):
            self.override_remain_short = getShortTime(self.on_override_end - tick_time)
            if tick_time >= self.on_override_end:
                self.state_over = None
        elif (self.state_over is False) and (self.off_logic == 'timer'):
            self.override_remain_short = getShortTime(self.off_override_end - tick_time)
            if tick_time >= self.off_override_end:
                self.state_over = None
        else:
            self.override_remain_short = ''

    #-------------------------------------------------------------------------------
    def updateIndigo(self):
        if self.state_changed:
            self.evaluate()
            state_list = [{'key':key,'value':self.states[key]} for key in self.k_update_states]
            self.dev.updateStatesOnServer(state_list)
            self.state_changed = False

    #-------------------------------------------------------------------------------
    def evaluate(self):
        if self.state_over is None:
            self.mode = 'auto'
            if self.state_auto:
                self.state = 'on-auto'
                self.on_state = True
            else:
                self.state = 'off-auto'
                self.on_state = False
        else:
            self.mode = 'over'
            if self.state_over:
                self.state = 'on-over'
                self.on_state = True
            else:
                self.state = 'off-over'
                self.on_state = False


    #-------------------------------------------------------------------------------
    def delta(self, cycles, units):
        multiplier = 1
        if units == 'minutes':
            multiplier = 60
        elif units == 'hours':
            multiplier = 60*60
        elif units == 'days':
            multiplier = 60*60*24
        return int(cycles)*multiplier

    #-------------------------------------------------------------------------------
    def getBoolValue(self, value, reverse=False):
        result = False
        try:
            result = bool(int(value))
        except:
            if isinstance(value, basestring):
                result = value.lower() in k_commonTrueStates
        if reverse:
            result = not result
        return result

    #-------------------------------------------------------------------------------
    def setOutputState(self, on_state):
        if self.output_type == 'device':
            for device_id in self.output_device_ids:
                try:
                    device = indigo.devices[int(device_id)]
                    if isinstance(device, indigo.SpeedControlDevice):
                        indigo.speedcontrol.setSpeedIndex(device, self.speedControlIndex[on_state])
                    elif isinstance(device, indigo.DimmerDevice):
                        indigo.dimmer.setBrightness(device, self.dimmerControlLevel[on_state])
                    else:
                        self.relayControlFunction[on_state](device)
                except KeyError:
                    self.logger.error(u'Device {} does not exist.  Reconfigure "{}".'.format(device_id,self.dev.name))
        elif self.output_type == 'action':
            try:
                action_id = [self.action_off,self.action_on][on_state]
                indigo.actionGroup.execute(self.action_id)
            except KeyError:
                self.logger.error(u'Action Group {} does not exist.  Reconfigure "{}".'.format(action_id,self.dev.name))

    #-------------------------------------------------------------------------------
    # properties
    #-------------------------------------------------------------------------------
    @property
    def name(self):
        return self.dev.name

    #-------------------------------------------------------------------------------
    def _stateGet(self):
        return self.states['state']
    def _stateSet(self, value):
        if self.states['state'] != value:
            self.states['state'] = value
            self.state_changed = True
    state = property(_stateGet,_stateSet)

    #-------------------------------------------------------------------------------
    def _modeGet(self):
        return self.states['mode']
    def _modeSet(self, value):
        if self.states['mode'] != value:
            self.states['mode'] = value
            self.state_changed = True
    mode = property(_modeGet,_modeSet)

    #-------------------------------------------------------------------------------
    def _autoGet(self):
        return self.states['state_auto']
    def _autoSet(self, value):
        if self.states['state_auto'] != value:
            self.logger.info('"{}" automatic {}'.format(self.dev.name,['off','on'][value]))
            self.states['state_auto'] = value
            self.state_changed = True
    state_auto = property(_autoGet,_autoSet)

    #-------------------------------------------------------------------------------
    def _overGet(self):
        try:
            return self.k_triple[self.states['state_over']]
        except:
            return None
    def _overSet(self, value):
        if value is True:
            if self.on_logic == 'timer':
                self.on_override_end = time.time() + self.on_over_duration
            elif self.on_logic == 'cancel':
                value = None
            elif self.on_logic == 'ignore':
                value = self.state_over
        elif value is False:
            if self.off_logic == 'timer':
                self.off_override_end = time.time() + self.off_over_duration
            elif self.off_logic == 'cancel':
                value = None
            elif self.off_logic == 'ignore':
                value = self.state_over
        if self.states['state_over'] != str(value).lower:
            self.logger.info('"{}" override {}'.format(self.dev.name,['off','on'][value]))
            self.states['state_over'] = str(value).lower()
            self.state_changed = True
    state_over = property(_overGet,_overSet)

    #-------------------------------------------------------------------------------
    def _onStateGet(self):
        return self.states['onOffState']
    def _onStateSet(self, value):
        if self.states['onOffState'] != value:
            self.setOutputState(value)
            self.states['onOffState'] = value
    on_state = property(_onStateGet,_onStateSet)

    #-------------------------------------------------------------------------------
    def _onTimeEndGet(self):
        return self.states['on_override_end']
    def _onTimeEndSet(self, value):
        if self.states['on_override_end'] != value:
            self.states['on_override_end'] = value
            self.state_changed = True
    on_override_end = property(_onTimeEndGet,_onTimeEndSet)

    #-------------------------------------------------------------------------------
    def _offTimeEndGet(self):
        return self.states['off_override_end']
    def _offTimeEndSet(self, value):
        if self.states['off_override_end'] != value:
            self.states['off_override_end'] = value
            self.state_changed = True
    off_override_end = property(_offTimeEndGet,_offTimeEndSet)

    #-------------------------------------------------------------------------------
    def _overrideRemainGet(self):
        return self.states['override_remain_short']
    def _overrideRemainSet(self, value):
        if self.states['override_remain_short'] != value:
            self.states['override_remain_short'] = value
            self.state_changed = True
    override_remain_short = property(_overrideRemainGet,_overrideRemainSet)

################################################################################
# Utilities
################################################################################
def validateTextFieldNumber(rawInput, numType=float, zero=True, negative=True):
    try:
        num = numType(rawInput)
        if not zero:
            if num == 0: raise
        if not negative:
            if num < 0: raise
        return True
    except:
        return False

################################################################################
def getShortTime(seconds):
    minutes = int(seconds/60)
    # If time is zero (or less) then show nothing
    if minutes <= 0:
        return ''
    # If time is less than 1 min then show <1m
    elif minutes < 1:
        return '<1m'
    # If time is less than 100 min then show XXm
    elif minutes < 100:
        return '{:.0f}m'.format(minutes)
    # If time is less than 49 hours then show XXh
    elif minutes < 2881:
        return '{:.0f}h'.format(minutes/60)
    # If time is less than 100 days then show XXd
    elif minutes < 144000:
        return '{:.0f}d'.format(minutes/1440)
    # If time is anything more than one hundred days then show 99+
    else:
        return '99+'
