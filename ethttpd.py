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
          'GATEWAY_INTERFACE': 'CGI/1.2',
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
        for i in range(1, len(reqlines)):
            colonindex = reqlines[i].find(':')
            if colonindex == -1:
                continue
            key = reqlines[i][:colonindex]
            value = reqlines[i][colonindex + 2:] # strip ": "
            attrs[key] = value 

        # horrible idea
        # if uri.startswith('/'):
        #     uri = uri[1:]

        # if uri.endswith('/'):
        #     # TODO: index.php html py, etc
        #     uri += 'index.html'

        pos = uri.find('?')
        if pos != -1:
            conn.filename = os.path.normpath(DOCUMENT_ROOT + uri[:pos])
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
        pprint.pprint(headers)

        value = headers.get('Status')
        if value:
            conn.http_code = int(value[:3])

        value = headers.get('Connection', '')
        conn.keepalive = True if value.lower() == 'keep-alive' else False 

        # aaaaa
        conn.sockfd.send('HTTP/1.1 %d ET\r\n' % conn.http_code)

def handle_cgi(conn):
    print 'handle_cgi'
    read_end, write_end = os.pipe()
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
        #cgienv['QUERY_STRING'] = conn.remote_ip 
        cgienv['REDIRECT_STATUS'] = '200'
        cgienv['REQUEST_URI'] = conn.uri
        cgienv['HTTP_HOST'] = conn.attrs['Host']
        cgienv['HTTP_CONNECTION'] = 'keep-alive' if conn.keepalive else 'close'
        if conn.query_string:
            cgienv['QUERY_STRING'] = conn.query_string

        pprint.pprint(cgienv)

        os.close(read_end)
        os.dup2(write_end, sys.stdout.fileno())
        os.execve('/usr/bin/php5-cgi', ['php5-cgi', conn.uri], cgienv)
    else: # parent
        try:
            response = ''
            os.close(write_end)
            isfirst = True
            while True:
                data = os.read(read_end, 4096)
                print '+-' * 20
                print data
                print '+=' * 20
                if not data:
                    print 'return not data'
                    break
                response += data
            os.close(read_end)
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

    ext = os.path.splitext(conn.filename)[1]
    ext = ext[1:] if ext.startswith('.') else ext

    # check cgi
    if ext in cgiexts:
        conn.state = State.CGI
        return

    # static file
    conn.state = State.REPLY_FROM_FILE
    conn.http_code = 200
    conn.http_msg = 'OK' 
    conn.reply_fd = f
    conn.headers['Content-Type'] = get_mime(ext)
    conn.headers['Content-Length'] = str(file_size)

    pprint.pprint(vars(conn))

def handle_request(conn):
    if conn.method == 'GET':
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

            pprint.pprint(vars(conn))

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
