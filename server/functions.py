#!/usr/bin/python26

#import sqlobject
from dbclasses import *

# TODO: generate auth_keys and remove DB_LOGIN

class ServerFunctions:
    def __init__(self, AUTH_KEY, DB_LOGIN):
        self.data = None
        self.asset_ip = '0.0.0.0'
        self.auth_key = AUTH_KEY
        self.is_authenticated = False

        # Create logger.
        #self.logger = logging.getLogger("secinv")

        #self.connect_database(DB_LOGIN)

    #def connect_database(self, DB_LOGIN):
        # To suppress MySQLdb DeprecationWarning.
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)

        self.cursor = None

        # TODO: add support for other DB engines
        if DB_LOGIN['engine'] == 'mysql':
            import MySQLdb
            import MySQLdb.cursors


            #self.connection = DBConnect()

            db = MySQLdb.connect(host=DB_LOGIN['host'],
                                 user=DB_LOGIN['user'],
                                 passwd=DB_LOGIN['passwd'],
                                 db=DB_LOGIN['db'],
                                 cursorclass=MySQLdb.cursors.DictCursor)
            self.cursor = db.cursor()

    def authenticate(self, auth_key):
        '''
        Compare server's auth_key against client's auth_key.
        '''
        if self.auth_key != auth_key:
            return False

        self.is_authenticated = True
        return True

    def assets(self, assets_dict):
        if not self.is_authenticated:
            return False

        self.cursor.execute("""SELECT COUNT(*) as c FROM history
                               WHERE asset_ip = '%s'""" % self.asset_ip)
        count = self.cursor.fetchone()
        count = int(count['c'])
        if count:
            # Update 'date_scanned' field for this system.
            self.cursor.execute("""UPDATE history SET date_scanned = NOW()
                                   WHERE asset_ip = '%s'""" % self.asset_ip)
        else:
            # Add a row for this system.
            self.cursor.execute("""INSERT INTO history (asset_ip, date_scanned)
                                   VALUES ('%s', NOW())""" % self.asset_ip)


        self.cursor.execute("""SELECT COUNT(*) as c, hostname, httpd, mysqld,
                               openvpn, nfs, kernel_rel, rh_rel FROM assets
                               WHERE sysip = '%s'""" % self.asset_ip)
        assets_row = self.cursor.fetchone()
        count = int(assets_row['c'])
        is_same = False

        if count:
            '''
            self.cursor.execute("""UPDATE assets SET hostname = '%s',
                                   httpd = '%s', mysqld = '%s', openvpn = '%s',
                                   nfs = '%s', kernel_rel = '%s', rh_rel = '%s'
                                   WHERE sysip = '%s'""" %
                                (assets_dict['hostname'],
                                 assets_dict['httpd'],
                                 assets_dict['mysqld'],
                                 assets_dict['openvpn'],
                                 assets_dict['nfs'],
                                 assets_dict['kernel_rel'],
                                 assets_dict['rh_rel'],
                                 self.asset_ip))
            '''

            del assets_row['c']
            for k, old_v in assets_row.iteritems():
                if assets_dict[k] == old_v:
                    is_same = True

        # Insert a row only if the assets values have changed.
        if not is_same:
            # TODO: 'ext_ip'?
            self.cursor.execute("""INSERT INTO assets (date_added, hostname,
                                   sysip, httpd, mysqld, openvpn, nfs,
                                   kernel_rel, rh_rel)
                                   VALUES (NOW(), '%s', '%s', '%s', '%s', '%s',
                                   '%s', '%s')""" %
                                (assets_dict['hostname'],
                                 self.asset_ip,
                                 assets_dict['httpd'],
                                 assets_dict['mysqld'],
                                 assets_dict['openvpn'],
                                 assets_dict['nfs'],
                                 assets_dict['kernel_rel'],
                                 assets_dict['rh_rel']))


        print "\nInserted into assets:", assets_dict

        self.cursor.execute("""SELECT * FROM assets""")
        self.cursor.fetchall()

        for rows in self.cursor:
            print ''.join(str(rows))


        return True

    def assets_ip(self, assets_ip_dict):
        if not self.is_authenticated:
            return False

        # TODO: Check if exists: insert or update.

        asset_ip = '0.0.0.0'
        for interface in assets_ip_dict.keys():
            if interface[0:3] == 'eth':
                asset_ip = assets_ip_dict[interface]['i_ip']
                self.asset_ip = asset_ip

        for interface in assets_ip_dict.keys():
            if assets_ip_dict[interface]['i_mac'] in ('00:00:00:00',
                                                      '00:00:00:00:00:00'):
                assets_ip_dict[interface]['i_mac'] = ''

            # If all fields are empty, do not insert a row for inactive device.
            if assets_ip_dict[interface]['i_ip'] == '' and \
               assets_ip_dict[interface]['i_mac'] == '' and \
               assets_ip_dict[interface]['i_mask'] == '':
                continue

            # If already exists in table, update row(s) accordingly.
            self.cursor.execute("""SELECT COUNT(*) as c FROM assets_ip
                                   WHERE asset_ip = '%s'""" % asset_ip)
            assets_ip_row = self.cursor.fetchone()
            count = int(assets_ip_row['c'])

            is_same = False
            if count:
                del assets_ip_row['c']
                for k, old_v in assets_ip_row.iteritems():
                    if assets_ip_dict[k] == old_v:
                        is_same = True

            if not is_same:
                # Insert a row only if the assets_ip values have changed.
                self.cursor.execute("""INSERT INTO assets_ip (asset_ip, i_name,
                                 i_ip, i_mac, i_mask)
                                  VALUES ('%s', '%s', '%s', '%s', '%s')""" %
                                   (asset_ip,
                                    interface,
                                    assets_ip_dict[interface]['i_ip'] if \
                                    interface[0:3] != 'eth' else '',
                                    assets_ip_dict[interface]['i_mac'],
                                    assets_ip_dict[interface]['i_mask']))

        print "\nInserted into assets_ip:", assets_ip_dict

        self.cursor.execute("""SELECT * FROM assets_ip""")
        self.cursor.fetchall()

        for rows in self.cursor:
            print ''.join(str(rows))

        return True

    def rpms(self, rpms_dict):
        if not self.is_authenticated:
            return False

        print "\nInserted into rpms:" #, rpms_dict

        return True

    def ports(self, ports_dict):
        if not self.is_authenticated:
            return False

        print "\nInserted into ports:", ports_dict

        # Clear all ports from last scan for this asset_ip.
        # TODO: Do not delete if unchanged.
        self.cursor.execute("""DELETE FROM assets_ports WHERE asset_ip = '%s'""" %
                            self.asset_ip)

        for k, v in ports_dict.iteritems():
            self.cursor.execute("""INSERT INTO assets_ports (asset_ip, process,
                                   port, date_added)
                                   VALUES ('%s', '%s', '%s', NOW())""" %
                                (self.asset_ip, k, v))

        return True
