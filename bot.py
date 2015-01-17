import imp
import os
import Queue
import re
import threading
import time
import traceback

import modules
import slack

home = os.getcwd()


class _SlackBotWrapper(object):
    def __init__(self, bot, msg):
        self._bot = bot
        self._msg = msg

    def reply(self, message):
        self.send(message, self._msg[u'channel_name'])

    def __getattr__(self, other):
        """Default to _bot's methods"""
        return getattr(self._bot, other)


class SlackBot(object):
    def __init__(self):
        self._incoming_messages = Queue.Queue()

        self._slack_api = slack.SlackAPI()
        self._slack_api.connect()
        self._slack_api.start_listening(self._listener)
        t = threading.Thread(target=self._dispatcher)
        t.setDaemon(True)
        t.start()

        self.commands = []
        self.load_all_modules()

    def _listener(self, message):
        """
        The listener simply enqueues the message to ensure we're
        able to listen for any further messages immediately.
        """
        self._incoming_messages.put(message)

    def send(self, text, channel):
        if not text:
            return
        channel = self._slack_api.get_channel_id(channel)
        message = dict(
            type="message",
            channel=channel,
            text=text,
        )
        self._slack_api.send(message)

    def _format_incoming(self, incoming):
        if u'channel' in incoming:
            incoming[u'channel_name'] = self._slack_api.get_channel_name(
                incoming[u'channel'])
        if u'user' in incoming:
            username = self._slack_api.get_nick(incoming[u'user'])
            if username:
                incoming[u'user_name'] = username

    def _dispatcher(self):
        """
        Receive messages and route them to functionality.
        """
        while 1:
            try:
                response = self._incoming_messages.get(block=True)
                self._format_incoming(response)
                now = time.time()
                # match the event to the best command
                for command in self.commands[:]:
                    if command.deadline is not False and command.deadline < now:
                        self.unregister_command(command)  # silently remove him
                        continue
                    match = command.matches(response)
                    if match:
                        command(_SlackBotWrapper(self, response), response, *match.groups())
                        if command.activations is not False and command.activations <= 0:
                            self.unregister_command(command)
            except Exception as e:
                traceback.print_exc()
                print response
            else:
                print response

    def get_module_path(self, name):
        """Get the path to the module of the given name."""
        return os.path.join(home, 'modules', '%s.py' % name)

    def find_module_paths(self):
        """Find all the files in /modules/"""
        filenames = []
        for mod in os.listdir(os.path.join(home, 'modules')):
            if mod.endswith('.py') and not mod.startswith('_'):
                filenames.append(os.path.join(home, 'modules', mod))
        return filenames

    def load_all_modules(self):
        """Load all the modules from the /modules/ directory"""
        for filename in self.find_module_paths():
            name = os.path.basename(filename)[:-3]
            self.load_module(name, filename)

    def load_module(self, name, filename=None):
        """
        Load a module, overwriting the previous module if possible
        Return an Exception, or None if no exception.
        """
        if filename is None:
            filename = self.get_module_path(name)
        cmds = self.commands[:]  # backup the commands (in case of failure)
        module_cmds = None
        if name in modules.register.modules:
            # unload the old module to make room for the new one, but remember it
            # in case something goes wrong when loading the new module.
            module_cmds = self.unload_module(name)
        try:
            # commands are registered automatically
            module = imp.load_source(name, filename)
            # # If you decide to use a setup method uncomment this,
            # # although actually it would probably be better as an
            # # explicit decorator. Ones for 'onload', 'onunload',
            # # stuff like that.
            # if hasattr(module, "setup"):
            #     module.setup()
        except Exception as e:
            print >> sys.stderr, "Error loading %s: %s (in bot.py)" % (name, e)
            self.commands = cmds  # replace commands' previous state
            if module_cmds is not None:
                modules.register.load_module(name, module_cmds)  # reload module's previous state
            elif name in modules.register.modules:  # loaded a couple commands
                modules.register.unload_module(name)
            return e
        else:
            commands = modules.register.module(name)
            if commands is not None:
                self.register_commands(commands)
        return None

    def register_commands(self, commands):
        self.commands.extend(commands)
        self.commands.sort(key=lambda cmd: -cmd.priority)

    def unregister_command(self, command):
        # TODO: Since commands are priority-ordered you could binary search
        self.commands.remove(command)
        modules.register.unregister_command(command)

    def unload_module(self, module_id):
        unregistered_commands = modules.register.unload_module(module_id)
        for command in unregistered_commands:
            # TODO: Also binary search here?
            self.commands.remove(command)
        return unregistered_commands


frankling = SlackBot()


while 1:
    message = raw_input()
    frankling.send(message, channel="bot_test")