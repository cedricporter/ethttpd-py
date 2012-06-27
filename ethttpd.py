#!/usr/bin/env python
# author:  Hua Liang [ Stupid ET ]
# email:   et@everet.org
# website: http://EverET.org
#

# Rule Of Optimization: Prototype before polishing. Get it
#                       working before you optimize it.

import socket, os, threading, sys, signal, stat
import time, struct, re, traceback
import pprint, ettools

host = ''
port = 12345
timeout = 5
DOCUMENT_ROOT = os.getcwd() + '/'

HTTP_PROTOCOL = 'HTTP/1.1'

cgiexts = ['cgi', 'php', 'sh', 'py']

cgienv = {'SERVER_SOFTWARE': 'ethttpd-py',
          'SERVER_NAME': 'localhost',
          'SERVER_PORT': str(port),
          'GATEWAY_INTERFACE': 'CGI/1.1',
          'SERVER_PROTOCOL': 'HTTP/1.1',}

mimes = {"application/ogg":      " ogg",
         "application/pdf":      " pdf",
         "application/xml":      " xsl xml",
         "application/xml-dtd":  " dtd",
         "application/xslt+xml": " xslt",
         "application/zip":      " zip",
         "audio/mpeg":           " mp2 mp3 mpga",
         "image/gif":            " gif",
         "image/jpeg":           " jpeg jpe jpg",
         "image/png":            " png",
         "text/css":             " css",
         "text/html":            " html htm",
         "text/javascript":      " js",
         "text/plain":           " txt asc",
         "video/mpeg":           " mpeg mpe mpg",
         "video/quicktime":      " qt mov",
         "video/x-msvideo":      " avi",}

# refine mimes for better use
mm = {}
for t in mimes.keys():
    for ext in mimes[t].split():
        mm[ext] = t
mimes = mm 


def get_mime(ext):
    'Get mime type by extension, ignore case'
    return mimes.get(ext.lower(), 'application/octet-stream')

class State:
    REPLY_FROM_FILE = 0
    REPLY_DIRECT = 1
    CGI = 2

class Connection(object):
    #@ettools.printargs
    def __init__(self, sockfd, remote_ip):
        self.sockfd = sockfd
        self.remote_ip = remote_ip
        self.uri = ''
        self.query_string = ''
        self.filename = ''
        self.request = None
        self.state = None
        self.http_code = -1
        self.http_msg = ''
        self.headers = {}
        self.reply_fd = None
        self.reply_html = ''
        self.keepalive = False

# class Request(object):
#     def __init__(self):
#         self.method = None
#         self.uri = ''
#         self.query_string = ''
#         self.filename = ''
#         self.attrs = None
#         self.body = None

def init(): 
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(5) 
    return s

def parse_http(conn, req_text):
    try:
        reqlines = req_text.splitlines()
        reqline = reqlines[0]
        method, uri, protocol = reqline.split() 
        attrs = {}
        body_index = -1
        for i in range(1, len(reqlines)):
            if method == 'POST' and len(reqlines[i]) == 0:
                body_index = i
                pprint.pprint(reqlines[body_index:])
                conn.body = '\r\n'.join(reqlines[body_index + 1:])
                break
            colonindex = reqlines[i].find(':')
            if colonindex == -1:
                continue
            key = reqlines[i][:colonindex]
            value = reqlines[i][colonindex + 2:] # strip ": "
            attrs[key] = value 

        pos = uri.find('?')
        if pos != -1:
            u = DOCUMENT_ROOT + uri[:pos]
            # FIXME
            if u.endswith('/'):
                u += 'index.php' 
            conn.filename = os.path.normpath(u)
            conn.query_string = uri[pos + 1:]
        else:
            u = uri
            if uri.endswith('/'):
                u = uri + 'index.php' 
            conn.filename = os.path.normpath(DOCUMENT_ROOT + u)

        conn.method = method
        conn.uri = uri
        conn.attrs = attrs

        conn.keepalive = True if attrs.get('Connection', '').lower() == 'keep-alive'\
            else False
        if conn.keepalive:
            conn.headers['Connection'] = 'Keep-Alive' 
            conn.headers['Keep-Alive'] = 'timeout=%d' % (timeout, )
    except Exception, e:
        traceback.print_exc()
        return -1

    return 0

def php_handle(conn):
    pass

def cgi_response_parse(conn, response):
    if response.startswith('HTTP/1.'):
        if (response[7] == '1' or response[7] == '0') and response[8] == ' ':
            status = response[8:10]
            status = int(status)
            if 0 <= status < 1000:
                # good
                conn.http_code = status
    else:
        header = response[:re.search(r'\r?\n\r?\n', response).start()]
        headers = {}
        for line in header.splitlines():
            key, value = line.split(': ')
            headers[key] = value
        #pprint.pprint(headers)

        value = headers.get('Status')
        if value:
            conn.http_code = int(value[:3])
            conn.http_msg = value[4:]

        value = headers.get('Connection', '')
        conn.keepalive = True if value.lower() == 'keep-alive' else False 

        # aaaaa
        conn.sockfd.send('HTTP/1.1 %d %s\r\n' % (conn.http_code, conn.http_msg))

def handle_cgi(conn):
    print 'handle_cgi'
    from_cgi_read_end, from_cgi_write_end = os.pipe()
    try:
        to_cgi_read_end, to_cgi_write_end = os.pipe()
    except:
        os.close(from_cgi_read_end)
        os.close(from_cgi_write_end)

    try:
        pid = os.fork()
    except:
        return -1
    if pid == 0: # child
        cgienv['REQUEST_METHOD'] = conn.method
        # SCRIPT_FILENAME is VERY important.
        cgienv['SCRIPT_FILENAME'] = conn.filename
        cgienv['SCRIPT_NAME'] = os.path.basename(conn.filename)
        cgienv['REMOTE_ADDR'] = conn.remote_ip
        cgienv['DOCUMENT_ROOT'] = DOCUMENT_ROOT
        cgienv['REDIRECT_STATUS'] = 'CGI'
        cgienv['REQUEST_URI'] = conn.uri
        cgienv['HTTP_HOST'] = conn.attrs['Host']
        cgienv['HTTP_CONNECTION'] = 'keep-alive' if conn.keepalive else 'close'
        if conn.query_string:
            cgienv['QUERY_STRING'] = conn.query_string
        if conn.attrs.get('Content-Length'):
            cgienv['CONTENT_LENGTH'] = conn.attrs['Content-Length']
        if conn.attrs.get('Content-Type'):
            cgienv['CONTENT_TYPE'] = conn.attrs['Content-Type']
        if conn.attrs.get('Referer'):
            cgienv['HTTP_REFERER'] = conn.attrs['Referer']
        if conn.attrs.get('Cookie'):
            cgienv['HTTP_COOKIE'] = conn.attrs['Cookie']

        # pprint.pprint(vars(conn))
        # pprint.pprint(cgienv)

        # move stdout to from_cgi_write_end
        os.close(sys.stdout.fileno())
        os.dup2(from_cgi_write_end, sys.stdout.fileno())
        os.close(from_cgi_write_end)
        # not needed
        os.close(from_cgi_read_end)

        # move stdin to to_cgi_read_end
        os.close(sys.stdin.fileno())
        os.dup2(to_cgi_read_end, sys.stdin.fileno())
        os.close(to_cgi_read_end)
        # not needed
        os.close(to_cgi_write_end)

        if conn.filename.endswith('.php'):
            os.execve('/usr/bin/php5-cgi', ['php5-cgi', conn.filename], cgienv)
        else:
            os.execve(conn.filename, (conn.filename, ), cgienv)

        os.abort()
    else: # parent
        try:
            os.close(to_cgi_read_end)
            os.close(from_cgi_write_end)
            if conn.method == 'POST':
               # print 'post ' * 50 
               # print conn.body
               # print '#' * 30
               os.write(to_cgi_write_end, conn.body)
            response = ''
            isfirst = True
            while True:
                data = os.read(from_cgi_read_end, 4096)
                # print '+-' * 20
                # print data
                # print '+=' * 20
                if not data:
                    print 'return not data'
                    break
                response += data
            os.close(to_cgi_write_end)
            os.close(from_cgi_read_end)
            print '_+' * 20
        except:
            traceback.print_exc()
        cgi_response_parse(conn, response)
        if conn.http_code == -1:
            conn.sockfd.send('HTTP/1.1 200 OK\r\n')
        conn.sockfd.send(response) 

    return 0 

def make_direct_reply(conn, code, msg, html):
    conn.state = State.REPLY_DIRECT
    conn.reply_html = html
    conn.http_code = code
    conn.http_msg = msg
    conn.headers['Content-Type'] = 'text/html'
    conn.headers['Content-Length'] = str(len(html))

def handle_get(conn):
    '''handle GET method'''
    print 'uri:', conn.uri
    print 'filename:', conn.filename

    # static ?

    # not a file, 404
    if not os.path.isfile(conn.filename):
        make_direct_reply(conn, 404, 'Not Found',
                          '404 Not Found You Wanted')
        return

    ext = os.path.splitext(conn.filename)[1]
    ext = ext[1:] if ext.startswith('.') else ext
    print '[extension]:', ext

    # check cgi
    if ext in cgiexts:
        conn.state = State.CGI
        return

    # privilege
    try:
        f = open(conn.filename, 'rb')
    except IOError, e:
        make_direct_reply(conn, 403, 'Forbidden',
                          'Permision Denied')
        return

    file_status = os.stat(conn.filename) 
    file_size = file_status[stat.ST_SIZE]
    modified_date = file_status[stat.ST_MTIME]

    # static file
    conn.state = State.REPLY_FROM_FILE
    conn.http_code = 200
    conn.http_msg = 'OK' 
    conn.reply_fd = f
    conn.headers['Content-Type'] = get_mime(ext)
    conn.headers['Content-Length'] = str(file_size)

def handle_request(conn):
    handle_get(conn)

def read_request(conn):
    data = conn.sockfd.recv(1 << 15)

    print '-' * 20
    print data
    print '^' * 20

    return data 

def reply_request(conn):
    '''assume that conn.reply_fd is valid if conn.state
       is REPLY_FROM_FILE
       '''
    if conn.state == State.CGI:
        handle_cgi(conn)
        return

    status_line = '%s %d %s\r\n' % (
        HTTP_PROTOCOL, conn.http_code, conn.http_msg)
    headers = conn.headers
    headers = '\r\n'.join((': '.join((key, headers[key])) for key in headers))

    conn.sockfd.send(status_line)
    conn.sockfd.send(headers)
    conn.sockfd.send('\r\n\r\n')

    if conn.state == State.REPLY_DIRECT:
        conn.sockfd.send(conn.reply_html)
    elif conn.state == State.REPLY_FROM_FILE:
        while True:
            data = conn.reply_fd.read(8192)
            if len(data) == 0: break
            conn.sockfd.send(data)
        conn.reply_fd.close()

def handle_connection(conn):
    try:
        while True:
            # temp here 
            conn.request = None
            conn.state = None
            conn.http_code = -1
            conn.http_msg = ''
            conn.headers = {}
            conn.reply_fd = None
            conn.reply_html = ''
            conn.keepalive = False

            data = read_request(conn)

            if not data:
                break

            if parse_http(conn, data) == -1:
                return -1

            handle_request(conn)

            reply_request(conn)

            if not conn.keepalive:
                break
    except socket.error:
        pass
        # print 'socket ' * 5
        # traceback.print_exc()

class thread_run(threading.Thread):
    def __init__(self, conn):
        threading.Thread.__init__(self)
        self.conn = conn
    def run(self):
        handle_connection(self.conn)
        self.conn.sockfd.close()
        print '[', self.getName(), ']', 'ended'

def multithread_run(sock): 
    while True:
        clientfd, clientaddr = sock.accept() 

        # timeout for 5 seconds
        clientfd.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO,
                            struct.pack('ll', timeout, 0))

        # select, fork or multithread
        conn = Connection(clientfd, clientaddr[0]) 

        th = thread_run(conn)
        th.start()

run = multithread_run

if __name__ == '__main__':
    sock = init()
    run(sock)
