import os
import sys
import time
from threading import Thread

import rumps

from app import common
from .res.const import Const
from .res.language import load_language, LANGUAGES
from .res.language.english import English
from .util import system_api, osa_api, github
from .config import Config
from .process_daemon import ProcessDaemon


class Application:
    def __init__(self):
        common.log('app_init', 'Info', 'version: %s' % Const.version, system_api.get_system_version())

        Config.load()

        self.is_admin = system_api.check_admin()

        self.lang = load_language(Config.language)

        self.app = rumps.App(Const.app_name, quit_button=None)

        self.pd_noidle = ProcessDaemon('/usr/bin/pmset noidle')

        self.menu = {}
        self.menu_preferences = None  # type: rumps.MenuItem
        self.menu_advanced_options = None  # type: rumps.MenuItem
        self.menu_select_language = None  # type: rumps.MenuItem
        self.menu_disable_idle_sleep = None  # type: rumps.MenuItem
        self.menu_disable_lid_sleep = None  # type: rumps.MenuItem
        self.menu_disable_idle_sleep_in_charging = None  # type: rumps.MenuItem
        self.menu_disable_lid_sleep_in_charging = None  # type: rumps.MenuItem
        self.menu_low_battery_capacity_sleep = None  # type: rumps.MenuItem
        self.menu_check_update = None  # type: rumps.MenuItem
        self.menu_screen_save_on_lid = None  # type: rumps.MenuItem
        self.menu_short_time_cancel_screen_save = None  # type: rumps.MenuItem

        self.init_menu()
        self.battery_status = None  # type: dict
        self.lid_stat = None  # type: bool
        self.sleep_idle_time = -1

    def init_menu(self):
        def g_menu(name, title='', callback=None, parent=self.app.menu):
            """
            Generate rumps menu item and record menu data, make easy to manage.
            """
            if name == '-':
                parent.add(rumps.separator)
            elif isinstance(name, rumps.MenuItem):
                menu = name
                name = menu.title  # type: str
                menu.set_callback(callback)
                self.menu[name] = {
                    'object': menu, 'name': name, 'title': title, 'callback': callback, 'parent': parent}
            else:
                menu = rumps.MenuItem(name, callback=(
                    (lambda _: self.callback_menu(name)) if callback is not None else None))

                parent.add(menu)
                self.menu[name] = {'object': menu, 'name': name, 'title': title, 'callback': callback, 'parent': parent}

                return menu

        def g_switch_config_action(key: str):
            """
            Generate switch config field state menu callback function.
            :param key:
            :return: function
            """

            def switch(sender: rumps.MenuItem):
                sender.state = not sender.state
                setattr(Config, key, bool(sender.state))
                Config.save()

            return switch

        def g_config_input_action(key, description, hidden=False, to_int=False):
            """
            Generate config field input dialog menu callback function.
            """

            def set_input(sender: rumps.MenuItem):
                content = osa_api.dialog_input(sender.title, getattr(self.lang, description),
                                               str(getattr(Config, key, '')), hidden=hidden)

                if content is not None:
                    if to_int:
                        if isinstance(content, str) and content.isnumeric():
                            setattr(Config, key, int(content))
                    else:
                        setattr(Config, key, content)

                    Config.save()
                    return True

                return False

            return set_input

        # menu_application
        g_menu('view_percent')
        g_menu('view_status')
        g_menu('view_remaining')
        g_menu('-')

        def sleep_now(sender: rumps.MenuItem):
            if not self.sleep():
                self.message_box(sender.title, self.lang.unable_to_pmset)

        g_menu('sleep_now', callback=sleep_now)

        g_menu('display_sleep_now', callback=lambda _: system_api.sleep(display_only=True))

        g_menu('-')
        self.menu_disable_idle_sleep = g_menu('disable_idle_sleep',
                                              callback=lambda sender: self.set_idle_sleep(sender.state))

        def disable_lid_sleep(sender: rumps.MenuItem):
            if not self.set_lid_sleep(sender.state):
                self.message_box(sender.title, self.lang.unable_to_pmset)

        self.menu_disable_lid_sleep = g_menu('disable_lid_sleep',
                                             callback=disable_lid_sleep)

        g_menu('-')
        self.menu_preferences = g_menu('preferences', self.lang.menu_preferences)
        self.menu_select_language = g_menu('select_language', callback=lambda _: self.select_language())

        g_menu('-')
        self.menu_check_update = g_menu('check_update', callback=(
            lambda sender: Thread(target=self.check_update, args=(sender,)).start()
        ))

        g_menu('about', callback=lambda _: self.about())
        g_menu('-')
        g_menu('quit', callback=lambda _: self.quit())
        # menu_application end

        # menu_preferences
        g_menu('set_startup', callback=lambda _: self.set_startup, parent=self.menu_preferences)
        g_menu('-', parent=self.menu_preferences)

        set_low_battery_capacity = g_config_input_action(
            'low_battery_capacity', 'description_set_low_battery_capacity', to_int=True)
        g_menu('set_low_battery_capacity', callback=set_low_battery_capacity,
               parent=self.menu_preferences)

        set_low_time_remaining = g_config_input_action(
            'low_time_remaining', 'description_set_low_time_remaining', to_int=True)
        g_menu('set_low_time_remaining', callback=set_low_time_remaining,
               parent=self.menu_preferences)

        g_menu('-', parent=self.menu_preferences)

        self.menu_disable_idle_sleep_in_charging = g_menu(
            'disable_idle_sleep_in_charging', callback=g_switch_config_action('disable_idle_sleep_in_charging'),
            parent=self.menu_preferences)

        self.menu_disable_lid_sleep_in_charging = g_menu(
            'disable_lid_sleep_in_charging', callback=g_switch_config_action('disable_lid_sleep_in_charging'),
            parent=self.menu_preferences)

        g_menu('-', parent=self.menu_preferences)

        self.menu_screen_save_on_lid = g_menu(
            'screen_save_on_lid', callback=g_switch_config_action('screen_save_on_lid'), parent=self.menu_preferences)

        self.menu_short_time_cancel_screen_save = g_menu(
            'short_time_cancel_screen_save', callback=g_switch_config_action('short_time_cancel_screen_save'),
            parent=self.menu_preferences)

        g_menu('-', parent=self.menu_preferences)

        set_username = g_config_input_action('username', 'description_set_username')
        g_menu('set_username', callback=set_username, parent=self.menu_preferences)

        set_password = g_config_input_action('password', 'description_set_password', hidden=True)
        g_menu('set_password', callback=set_password, parent=self.menu_preferences)

        g_menu('-', parent=self.menu_preferences)
        self.menu_advanced_options = g_menu('advanced_options', parent=self.menu_preferences)

        # menu_preferences end

        # menu_select_language
        def g_set_lang(lang):
            """
            Generate set language menu callback function.
            """
            return lambda _: self.set_language(lang)

        for k in LANGUAGES:
            g_menu(k, LANGUAGES[k].l_this, g_set_lang(k),
                   parent=self.menu_select_language)
        # menu_select_language end

        # menu_advanced_options
        self.menu_low_battery_capacity_sleep = g_menu(
            'low_battery_capacity_sleep', callback=g_switch_config_action('low_battery_capacity_sleep'),
            parent=self.menu_advanced_options)

        g_menu('-', parent=self.menu_advanced_options)

        g_menu('set_sleep_mode', callback=self.set_sleep_mode,
               parent=self.menu_advanced_options)

        g_menu('-', parent=self.menu_advanced_options)

        g_menu('export_log', callback=lambda _: self.export_log(),
               parent=self.menu_advanced_options)

        g_menu('-', parent=self.menu_advanced_options)

        g_menu('clear_config', callback=lambda _: Config.clear(),
               parent=self.menu_advanced_options)
        # menu_advanced_options end

        # update menus title.
        for k, v in self.menu.items():
            if v['title'] is not None:
                v['object'].title = v['title']
                del v['title']
        self.refresh_menu_title()

        # inject value to menu.
        self.menu_disable_idle_sleep_in_charging.state = Config.disable_idle_sleep_in_charging
        self.menu_disable_lid_sleep_in_charging.state = Config.disable_lid_sleep_in_charging
        self.menu_low_battery_capacity_sleep.state = Config.low_battery_capacity_sleep
        self.menu_screen_save_on_lid.state = Config.screen_save_on_lid
        self.menu_short_time_cancel_screen_save.state = Config.short_time_cancel_screen_save

        [info, _] = system_api.sleep_info()
        self.menu_disable_lid_sleep.state = info.get('SleepDisabled', False)

    def refresh_menu_title(self):
        for k, v in self.menu.items():
            if 'menu_%s' % k in dir(self.lang):
                title = getattr(self.lang, 'menu_%s' % k)
                v['object'].title = title

    def admin_exec(self, command):
        code = -1

        if Config.username != '':
            code, out, err = osa_api.run_as_admin(command, Config.password, Config.username)
        else:
            if self.is_admin:
                code, out, err = system_api.sudo(command, Config.password)
                common.log(self.admin_exec, 'Info', {'command': command, 'status': code, 'output': out, 'error': err})

        if code != 0:
            return False

        return True

    def set_menu_title(self, name, title):
        self.app.menu[name].title = title

    def refresh_view(self):
        self.set_menu_title(
            'view_percent', self.lang.view_percent % self.battery_status['percent'])

        self.set_menu_title(
            'view_status', self.lang.view_status % (
                self.lang.status_charging.get(self.battery_status['status'], self.lang.unknown)))

        self.set_menu_title(
            'view_remaining', self.lang.view_remaining % (
                (self.lang.view_remaining_time % self.battery_status['remaining'])
                if self.battery_status['remaining'] is not None else self.lang.view_remaining_counting))

    def refresh_sleep_idle_time(self):
        [info, note] = system_api.sleep_info()
        if 'prevented' not in note.get('sleep', ''):
            self.sleep_idle_time = info.get('sleep', 0) * 60
        else:
            self.sleep_idle_time = -1

    def callback_menu(self, name):
        try:
            common.log(self.callback_menu, 'Info', 'Click %s.' % name)
            menu = self.menu[name]
            menu['callback'](menu['object'])
        except:
            self.callback_exception()

    def callback_refresh(self, sender: rumps.Timer):
        try:
            if self.menu_disable_lid_sleep.state:
                # check lid status
                lid_stat_prev = self.lid_stat
                self.lid_stat = system_api.check_lid()
                if self.lid_stat is not None:
                    if lid_stat_prev is None or lid_stat_prev != self.lid_stat:
                        self.callback_lid_status_changed(self.lid_stat, lid_stat_prev)

                # check idle sleep (on disable (lid) sleep)
                if not self.menu_disable_idle_sleep.state:
                    self.refresh_sleep_idle_time()
                    if self.sleep_idle_time > 0:
                        if system_api.get_hid_idle_time() >= self.sleep_idle_time:
                            self.sleep()

            # check battery status
            battery_status_prev = self.battery_status
            self.battery_status = system_api.battery_status()
            if self.battery_status is not None:
                if battery_status_prev is None:
                    self.callback_charge_status_changed(self.battery_status['status'])
                else:
                    if battery_status_prev['status'] != self.battery_status['status']:
                        self.callback_charge_status_changed(
                            self.battery_status['status'], battery_status_prev['status'])

                self.refresh_view()

                # low battery capacity sleep check
                if Config.low_battery_capacity_sleep:
                    if self.battery_status['status'] == 'discharging':
                        low_battery_capacity = self.battery_status['percent'] <= Config.low_battery_capacity

                        low_time_remaining = self.battery_status['remaining'] is not None \
                                             and self.battery_status['remaining'] <= Config.low_time_remaining

                        if low_battery_capacity or low_time_remaining:
                            self.sleep()
        except:
            sender.stop()
            self.callback_exception()

    def callback_lid_status_changed(self, status, status_prev=None):
        common.log(self.callback_lid_status_changed, 'Info', 'from "%s" to "%s"' % (status_prev, status))
        if status:
            if Config.screen_save_on_lid:
                if Config.short_time_cancel_screen_save:
                    @common.wait_and_check(3, 0.5)
                    def check_lock():
                        return system_api.check_lid()

                    valid = check_lock()
                    if valid:
                        osa_api.screen_save()
                    else:
                        common.log('check_lock', 'Info', 'user cancel lock screen.')
                else:
                    osa_api.screen_save()

    def callback_charge_status_changed(self, status, status_prev=None):
        common.log(self.callback_charge_status_changed, 'Info', 'from "%s" to "%s"' % (status_prev, status))
        self.refresh_sleep_idle_time()
        if status == 'discharging':
            if Config.disable_idle_sleep_in_charging:
                self.set_idle_sleep(True)
            if Config.disable_lid_sleep_in_charging:
                self.set_lid_sleep(True)
        elif status_prev in [None, 'discharging'] and status in ['not charging', 'charging', 'finishing charge',
                                                                 'charged']:
            if Config.disable_idle_sleep_in_charging:
                self.set_idle_sleep(False)
            if Config.disable_lid_sleep_in_charging:
                self.set_lid_sleep(False)

    def callback_exception(self):
        exc = common.get_exception()
        common.log(self.callback_exception, 'Error', exc)
        if osa_api.alert(self.lang.title_crash, self.lang.description_crash):
            self.export_log()

    def select_language(self):
        items = []
        for k in LANGUAGES:
            items.append(LANGUAGES[k].l_this)

        index = osa_api.choose_from_list(English.menu_select_language, English.description_select_language, items)
        if index is not None:
            language = None
            description = items[index]
            for k, v in LANGUAGES.items():
                if description == v.l_this:
                    language = k
                    break

            if language is not None:
                self.set_language(language)
                return True

        return False

    def set_startup(self):
        res = osa_api.alert(self.lang.menu_set_startup, self.lang.description_set_startup)
        if res:
            osa_api.set_login_startup(*common.get_application_info())

    def set_sleep_mode(self, sender: rumps.MenuItem):
        [info, _] = system_api.sleep_info()
        items = [self.lang.sleep_mode_0, self.lang.sleep_mode_3, self.lang.sleep_mode_25]
        items_value = {
            0: 0,
            1: 3,
            2: 25,
        }

        default = None
        for k, v in items_value.items():
            if v == info['hibernatemode']:
                default = k
        res = osa_api.dialog_select(sender.title, self.lang.description_set_sleep_mode % info['hibernatemode'],
                                    items, default)
        mode = items_value.get(res)
        if mode is not None and mode != info['hibernatemode']:
            system_api.set_sleep_mode(mode, self.admin_exec)

    def sleep(self):
        fix_idle_sleep = self.menu_disable_idle_sleep.state
        fix_lid_sleep = self.menu_disable_lid_sleep.state

        if fix_idle_sleep:
            self.set_idle_sleep(True)
        if fix_lid_sleep:
            self.set_lid_sleep(True)

        sleep_ready_time = 0
        sleep_begin_time = time.time()

        system_api.sleep()

        @common.wait_and_check(3600, 0.5)
        def check_ready():
            t = system_api.get_hid_idle_time()
            if t > 0.5:
                nonlocal sleep_ready_time
                sleep_ready_time = t
            return t > 0.5

        time.sleep(0.5)
        check_ready()

        real_sleep_time = time.time() - sleep_begin_time - sleep_ready_time
        common.log(self.sleep, 'Info',
                   'sleep_ready_time: %.2fs, real_sleep_time: %.2fs' % (sleep_ready_time, real_sleep_time))

        if fix_idle_sleep:
            self.set_idle_sleep(False)
        if fix_lid_sleep:
            self.set_lid_sleep(False)

        return real_sleep_time > 5

    def set_lid_sleep(self, available):
        self.menu_disable_lid_sleep.state = not available
        if available:
            success = system_api.set_sleep_available(True, self.admin_exec)
        else:
            success = system_api.set_sleep_available(False, self.admin_exec)

        if not success:
            [info, _] = system_api.sleep_info()
            self.menu_disable_lid_sleep.state = info.get('SleepDisabled', available)

        return success

    def set_idle_sleep(self, available):
        self.menu_disable_idle_sleep.state = not available
        if available:
            self.pd_noidle.stop()
        else:
            self.pd_noidle.start()

    def about(self, welcome=False):
        res = osa_api.dialog_input(self.lang.menu_about if not welcome else self.lang.title_welcome,
                                   self.lang.description_about % Const.version, Const.github_page)

        if isinstance(res, str):
            res = res.strip().lower()

        if res == ':export log':
            self.export_log()
        elif res == ':check update':
            self.check_update(self.menu_check_update, True)
        elif res == ':restart':
            self.restart()
        elif res == Const.github_page and not welcome:
            system_api.open_url(Const.github_page)

    def export_log(self):
        folder = osa_api.choose_folder(self.lang.menu_export_log)
        if folder is not None:
            log = common.extract_log()
            err = common.extract_err()

            if Config.password != '':
                log = log.replace(Config.password, Const.pwd_hider)
                err = err.replace(Config.password, Const.pwd_hider)

            if log != '':
                with open('%s/%s' % (folder, '%s.log' % Const.app_name), 'w') as io:
                    io.write(log)

            if err != '':
                with open('%s/%s' % (folder, '%s.err' % Const.app_name), 'w') as io:
                    io.write(err)

    def quit(self, reset_only=False):
        self.pd_noidle.stop()
        [info, _] = system_api.sleep_info()
        if info.get('SleepDisabled', False):
            system_api.set_sleep_available(True, self.admin_exec)

        if not reset_only:
            rumps.quit_application()

    def check_update(self, sender, test=False):
        try:
            release = github.get_latest_release(Const.author, Const.app_name, timeout=5)
            common.log(self.check_update, 'Info', release)

            if test or common.compare_version(Const.version, release['tag_name']):
                rumps.notification(
                    self.lang.noti_update_version % release['name'],
                    self.lang.noti_update_time % release['published_at'],
                    release['body'],
                )

                if sender == self.menu_check_update:
                    if len(release['assets']) > 0:
                        system_api.open_url(release['assets'][0]['browser_download_url'])
                    else:
                        system_api.open_url(release['html_url'])
            else:
                if sender == self.menu_check_update:
                    rumps.notification(sender.title, self.lang.noti_update_none, self.lang.noti_update_star)
        except:
            common.log(self.check_update, 'Warning', common.get_exception())
            if sender == self.menu_check_update:
                rumps.notification(sender.title, '', self.lang.noti_network_error)

    def message_box(self, title, description):
        return osa_api.dialog_select(title, description, [self.lang.ok])

    def welcome(self):
        self.about(True)
        self.select_language()

        self.message_box(self.lang.title_welcome, self.lang.description_welcome_why_need_admin)

        cancel_account = False

        if not self.is_admin:
            # set username
            menu_set_username = self.menu['set_username']
            if not menu_set_username['callback'](menu_set_username['object']) or Config.username == '':
                cancel_account = True
        else:
            self.message_box(self.lang.title_welcome, self.lang.description_welcome_is_admin)

        if not cancel_account:
            # set password
            menu_set_password = self.menu['set_password']
            if not menu_set_password['callback'](menu_set_password['object']):
                cancel_account = True

        if cancel_account:
            self.message_box(self.lang.title_welcome, self.lang.description_welcome_tips_set_account)

        self.message_box(self.lang.title_welcome, self.lang.description_welcome_end)

        Config.welcome = False
        Config.save()

    def run(self):
        if Config.welcome:
            self.welcome()

        t_refresh = rumps.Timer(self.callback_refresh, 1)
        t_refresh.start()
        self.app.icon = '%s/app/res/icon.png' % common.get_runtime_dir()
        self.app.run()

    def restart(self):
        self.quit(True)

        [_, path] = common.get_application_info()
        if path is not None:
            system_api.open_url(path, True)
        else:
            # quick restart for debug.
            self.app.title = '\x00'
            self.app.icon = None

            runtime_paths = []
            for x in sys.path:
                path = '%s/../../bin/python' % x
                if 'python' in x and os.path.isdir(x) and os.path.exists(path):
                    path = os.path.abspath(path)
                    runtime_paths.append(path)

            if len(runtime_paths) > 0:
                os.system('%s %s' % (runtime_paths[0], ' '.join(sys.argv)))

        rumps.quit_application()

    def set_language(self, language):
        self.lang = LANGUAGES[language]()
        self.refresh_menu_title()
        Config.language = language
        Config.save()
