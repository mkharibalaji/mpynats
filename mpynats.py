import usocket
import ujson
import utime
import uos
import ubinascii
import ure

NATS_SERVER_URL = ure.compile(b'^nats://(([^:^@.+]+):([^:^@.+]+)@)?([^:^@]+):([0-9]+)$')
MSG = ure.compile(b'MSG( )+([^ ]+)( )+([^ ]+)( )+(([^ ]+)( )+)?([0-9]+)$')
OK = ure.compile(b'^\+OK$')
ERR = ure.compile(b'^-ERR( )+(.+)?$') # match 1: space 2: 'Err Msg'
PING = ure.compile(b'^PING$')
PONG = ure.compile(b'^PONG$')
INFO = ure.compile(b'^INFO( )+(.+)(.+)$') # match 1: space 2: Info Msg
commands = {'+OK': OK, '-ERR': ERR,'PING': PING, 'PONG': PONG, 'INFO': INFO,'MSG' : MSG}

class Message(object):
    def __init__(self, sid, subject, size, data, reply=None):
        self.sid = sid
        self.subject = subject
        self.size = size
        self.data = data
        self.reply = reply

class Subscription(object):
    def __init__(self, sid, subject, queue, callback, connetion):
        self.sid = sid
        self.subject = subject
        self.queue = queue
        self.connetion = connetion
        self.callback = callback
        self.received = 0
        self.delivered = 0
        self.bytes = 0
        self.max = 0

    def handle_msg(self, msg):
        return self.callback(msg)

DEFAULT_URI = 'nats://192.168.1.3:4222'

class Connection(object):
    """
    A Connection represents a bare connection to a nats-server.
    """
    def __init__(
        self,
        url=DEFAULT_URI,
        name=None,
        ssl_required=False,
        verbose=False,
        pedantic=False,
        socket_keepalive=False,
        raw=False, 
        debug=False
    ):
        self._connect_timeout = None
        self._socket_keepalive = socket_keepalive
        self._socket = None
        self._socket_file = None
        self._subscriptions = {}
        self._next_sid = 1
        self._raw = raw
        self._debug=debug
        self._options = {
            'url': self._urlparse(url),
            'name': name,
            'ssl_required': ssl_required,
            'verbose': verbose,
            'pedantic': pedantic
        }

    def _urlparse(self, url):
        parsed_url = NATS_SERVER_URL.match(url)
        if parsed_url is None:
           raise NATSConnectionException('Expected : {} Given : {}'.format('nats://[<username>:<password>@]<host>:<port>', url))
        return {'host':parsed_url.group(4), 'port':int(parsed_url.group(5)), 'username':parsed_url.group(2), 'password':parsed_url.group(3)}

    def connect(self):
        """
        Connect will attempt to connect to the NATS server. The url can
        contain username/password semantics.
        """
        self._build_socket()
        self._connect_socket()
        self._build_file_socket()
        self._send_connect_msg()

    def _build_socket(self):
        self._socket = usocket.socket(usocket.AF_INET, usocket.SOCK_STREAM,usocket.IPPROTO_TCP)
        #SO_KEEPALIVE feture requested and will be added once Micropython adds it.
        #self._socket.setsockopt(usocket.IPPROTO_TCP, usocket.TCP_NODELAY, 1)
        #if self._socket_keepalive:
           #self._socket.setsockopt(usocket.SOL_SOCKET, usocket.SO_KEEPALIVE, 1)
        self._socket.settimeout(self._connect_timeout)

    def _connect_socket(self):
        SocketError.wrap(self._socket.connect, (
            self._options['url']['host'],
            self._options['url']['port']
        ))

    def _send_connect_msg(self):
        self._send('CONNECT %s' % self._build_connect_config())
        self._recv(INFO)

    def _build_connect_config(self):
        config = {
            'verbose': self._options['verbose'],
            'pedantic': self._options['pedantic'],
            'ssl_required': self._options['ssl_required'],
            'name': self._options['name'],
            'lang' : 'micropython',
            'version': '0.0.1'
        }

        if self._options['url']['username'] is not None:
            config['user'] = self._options['url']['username']
            config['pass'] = self._options['url']['password']

        return ujson.dumps(config)

    def _build_file_socket(self):
        self._socket_file = self._socket.makefile('rb')

    def ping(self):
        self._send('PING')
        self._recv(PONG)

    def subscribe(self, subject, callback, queue=''):
        """
        Subscribe will express interest in the given subject. The subject can
        have wildcards (partial:*, full:>). Messages will be delivered to the
        associated callback.

        Args:
            subject (string): a string with the subject
            callback (function): callback to be called
        """
        s = Subscription(
            sid=self._next_sid,
            subject=subject,
            queue=queue,
            callback=callback,
            connetion=self
        )

        self._subscriptions[s.sid] = s
        self._send('SUB %s %s %d' % (s.subject, s.queue, s.sid))
        self._next_sid += 1

        return s

    def unsubscribe(self, subscription, max=None):
        """
        Unsubscribe will remove interest in the given subject. If max is
        provided an automatic Unsubscribe that is processed by the server
        when max messages have been received

        Args:
            subscription (pynats.Subscription): a Subscription object
            max (int=None): number of messages
        """
        if max is None:
            self._send('UNSUB %d' % subscription.sid)
            self._subscriptions.pop(subscription.sid)
        else:
            subscription.max = max
            self._send('UNSUB %d %s' % (subscription.sid, max))

    def publish(self, subject, msg, reply=None):
        """
        Publish publishes the data argument to the given subject.

        Args:
            subject (string): a string with the subject
            msg (string): payload string
            reply (string): subject used in the reply
        """
        if msg is None:
            msg = ''

        if reply is None:
            command = 'PUB %s %d' % (subject, len(msg))
        else:
            command = 'PUB %s %s %d' % (subject, reply, len(msg))

        self._send(command)
        self._send(msg)

    def request(self, subject, callback, msg=None):
        """
        publish a message with an implicit inbox listener as the reply.
        Message is optional.

        Args:
            subject (string): a string with the subject
            callback (function): callback to be called
            msg (string=None): payload string
        """
        inbox = self._build_inbox()
        s = self.subscribe(inbox, callback)
        self.unsubscribe(s, 1)
        self.publish(subject, msg, inbox)

        return s

    def _random_choice(self,seq):
        a = int(utime.time() * 256) # use fractional seconds
        if not isinstance(a, int):
            a = hash(a)
        a, x = divmod(a, 30268)
        a, y = divmod(a, 30306)
        a, z = divmod(a, 30322)
        x, y, z = int(x)+1, int(y)+1, int(z)+1
        x = (171 * x) % 30269
        y = (172 * y) % 30307
        z = (170 * z) % 30323
        _random = (x/30269.0 + y/30307.0 + z/30323.0) % 1.0
        return seq[int(_random * len(seq))]
        
    def _build_inbox(self):
        #ascii_lowercase = 'abcdefghijklmnopqrstuvwxyz'
        #inbox_id = ''.join(self._random_choice(ascii_lowercase) for i in range(13))
        inbox_id = 'AAA666'
        while True:
            inbox_id = ure.match(r'\(?([a-zA-Z0-9]+)', ubinascii.b2a_base64(uos.urandom(16)).strip())
            if inbox_id is not None :
                inbox_id = inbox_id.group(1).upper()[2:8]
                if inbox_id and len(inbox_id) == 6 :
                    break
        if self._debug:
            print('Inbox ID : _INBOX.{}'.format(inbox_id))
        return "_INBOX.%s" % inbox_id

    def wait(self, duration=None, count=0):
        """
        Publish publishes the data argument to the given subject.

        Args:
            duration (float): will wait for the given number of seconds
            count (count): stop of wait after n messages from any subject
        """
        start = utime.time()
        total = 0
        while True:
            type, result = self._recv(MSG, PING, OK)
            if type is MSG:
                total += 1
                if self._handle_msg(result) is False:
                    break

                if count and total >= count:
                    break
            elif type is ERR:
                raise NATSError(result)
            elif type is PING:
                self._handle_ping()

            if duration and utime.time() - start > duration:
                break

    def _handle_msg(self, result):
        data = result
        sid = int(data['sid'])

        msg = Message(
            sid=sid,
            subject=data['subject'],
            size=int(data['size']),
            data=SocketError.wrap(self._readline).strip(),
            reply=data['reply'].strip() if data['reply'] is not None else None
        )

        s = self._subscriptions.get(sid)
        s.received += 1

        # Check for auto-unsubscribe
        if s.max > 0 and s.received == s.max:
            self._subscriptions.pop(s.sid)

        return s.handle_msg(msg)

    def _handle_ping(self):
        self._send('PONG')

    def reconnect(self):
        """
        Close the connection to the NATS server and open a new one
        """
        self.close()
        self.connect()

    def close(self):
        """
        Close will close the connection to the server.
        """
        self.close()

    def _send(self, command):
        #SocketError.wrap(self._socket.sendall, (command + '\r\n').encode('utf-8'))
        msg = command + '\r\n'
        if not self._raw:
            msg = msg.encode('utf-8')
        SocketError.wrap(self._socket.sendall, msg)

    def _readline(self):
        lines = []

        while True:
            line = self._socket_file.readline()
            if not self._raw:
                line = line.decode('utf-8')
            lines.append(line)

            if line.endswith("\r\n"):
                break

        return "".join(lines)

    def _recv(self, *args):
        line = SocketError.wrap(self._readline)
        command = self._get_command(line)
        if not self._raw:
            line = line.encode('utf-8')
        #INFO regex has issue with parsing long Text in MicroPython.
        #Todo Update the below Condition Once it is fixed in Micropython
        #https://github.com/micropython/micropython/issues/2451
        if (command is not INFO):
            result = command.match(line.strip())
        else:
            result = line
        if command in (OK, PING, PONG):
            result = result.group(0)
        elif command is ERR:
            result = result.group(2)
        elif command is MSG:
            result = {'subject': result.group(2),'sid': result.group(4),'reply': result.group(6),'size': result.group(9)}
        if result is None:
            raise NATSCommandException(command, line)
        if self._debug:
            print('>>{}<<'.format(result))
        return command, result

    def _get_command(self, line):
        values = line.strip().split(' ', 1)
        tmp_cmd = values[0].strip()
        tmp_command = commands.get(tmp_cmd)
        if tmp_command is None:
           raise NATSCommandException('Command {} not found.Allowed Commands : {}'.format(tmp_cmd, 'INFO,+OK,PING,PONG,MSG,-ERR'))
        return tmp_command

class NATSConnectionException(Exception):
    pass

class NATSCommandException(Exception):
    pass

class NATSError(Exception):
    pass

class SocketError(Exception):
    @staticmethod
    def wrap(wrapped_function, *args, **kwargs):
        try:
            return wrapped_function(*args, **kwargs)
        except usocket.error as err:
            raise NATSConnectionException(err)
