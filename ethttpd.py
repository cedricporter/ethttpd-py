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
from collections import defaultdict

host = ''
port = 12345
timeout = 15
DOCUMENT_ROOT = os.getcwd() + '/'

HTTP_PROTOCOL = 'HTTP/1.1'

cgiexts = ['cgi', 'php', 'sh', 'py']

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

default_files = set([
    'index.html',
    'index.php',
    ])

def handle_php(conn):
    handle_cgi(conn)

handlers = {}

class Request(object):
    def __init__(self, header):
        self.request = ''
        self.uri = ''
        self.orig_uri = ''
        self.http_method = ''
        self.http_version = ''
        self.request_line = ''
        self.headers = defaultdict(list)
        self.content_length = -1
        self.body = ''
        self.query_string = ''

        self._parse(header)

    def _parse(self, header):
        lines = header.splitlines()
        self.request_line = lines[0]
        method, uri, protocol = self.request_line.split()

        self.orig_uri = self.uri = uri
        qpos = uri.find('?')
        if qpos != -1:
            self.query_string = uri[qpos + 1:]
            self.uri = uri[:qpos]
        
        self.http_method = method
        self.http_version = protocol 

        for i in range(1, len(lines)):
            key, value = lines[i].split(': ')
            self.headers[key].append(value)

        self.content_length = self.headers.get('Content-Length', [-1])[0]

class Response(object):
    RESPONSE_FROM_FILE = 0
    RESPONSE_FROM_MEM = 1

    def __init__(self):
        self.content_length = -1
        self.keepalive = False
        self.headers = defaultdict(list)
        self.response_type = Response.RESPONSE_FROM_MEM
        self.response = ''
        self.response_fd = -1 
        
class Connection(object):
    def __init__(self, sockfd, remote_ip):
        self.sockfd = sockfd
        self.remote_ip = remote_ip
        self.keepalive = False

        self.reset()

    def reset(self):
        self.state = None
        self.keepalive = False
        self.http_status = -1
        self.request = None
        self.response = None
        self.environment = {}

class ThreadRun(threading.Thread):
    def __init__(self, conn):
        threading.Thread.__init__(self)
        self.conn = conn
    def run(self):
        handle_connection(self.conn)
        self.conn.sockfd.close()
        print '[', self.getName(), ']', 'ended'

class MultiThreadServer(object): 
    def __init__(self, host, port):
        self.listenfd = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listenfd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listenfd.bind((host, port))
        self.listenfd.listen(5) 

    def serve_forver(self):
        while True:
            clientfd, clientaddr = self.listenfd.accept() 

            # timeout for 5 seconds
            clientfd.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO,
                                struct.pack('ll', timeout, 0))

            # select, fork or multithread
            conn = Connection(clientfd, clientaddr[0]) 

            th = ThreadRun(conn)
            th.start()

def get_header(buf):
    'return header and end pos of header'
    r = re.search(r'\r*\n\r*\n', buf)
    header = buf[:r.start()]
    return header, r.end()

####################

def get_mime(ext):
    'Get mime type by extension, ignore case'
    return mimes.get(ext.lower(), 'application/octet-stream')

def cgi_response_parse(conn, cgi_response):
    print '=' * 50
    # print cgi_response

    if cgi_response.startswith('HTTP/1.'):
        if (cgi_response[7] == '1' or cgi_response[7] == '0') and cgi_response[8] == ' ':
            status = cgi_response[8:10]
            status = int(status)
            if 0 <= status < 1000:
                # good
                conn.http_status = status
    else:
        separtor = re.search(r'\r?\n\r?\n', cgi_response)
        header = cgi_response[:separtor.start()]
        headers = defaultdict(list)
        for line in header.splitlines():
            key, value = line.split(': ')
            headers[key].append(value)

        print 'cgi_response_parse', '|' * 100
        pprint.pprint(headers)

        value = headers.get('Status')
        if value:
            value = value[0]
            conn.http_status = int(value[:3])
            conn.http_msg = value[4:]
            del headers['Status']

        value = headers.get('Connection', [''])[0]
        conn.keepalive = True if value.lower() == 'keep-alive' else False 

        response = Response()
        response.response_type = Response.RESPONSE_FROM_MEM
        response.keepalive = conn.keepalive
        response.headers = headers
        response.response = cgi_response[separtor.end():]

        conn.response = response


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
        filename = os.path.normpath(DOCUMENT_ROOT + conn.request.uri)
        print 'CC' * 50
        print filename

        cgienv = {'SERVER_SOFTWARE': 'ethttpd-py',
                  'SERVER_NAME': 'localhost',
                  'SERVER_PORT': str(port),
                  'GATEWAY_INTERFACE': 'CGI/1.1',
                  'SERVER_PROTOCOL': 'HTTP/1.1',}

        cgienv['REQUEST_METHOD'] = conn.request.http_method
        # SCRIPT_FILENAME is VERY important.
        cgienv['SCRIPT_FILENAME'] = filename
        cgienv['SCRIPT_NAME'] = os.path.basename(filename)
        cgienv['REMOTE_ADDR'] = conn.remote_ip
        cgienv['DOCUMENT_ROOT'] = DOCUMENT_ROOT
        cgienv['REDIRECT_STATUS'] = '200'
        cgienv['REQUEST_URI'] = conn.request.orig_uri
        cgienv['HTTP_HOST'] = conn.request.headers['Host'][0]
        cgienv['HTTP_CONNECTION'] = 'Keep-Alive' if conn.keepalive else 'close'

        attrs = conn.request.headers
        if conn.request.query_string:
            cgienv['QUERY_STRING'] = conn.request.query_string
        if attrs.get('Content-Length'):
            cgienv['CONTENT_LENGTH'] = attrs['Content-Length'][0]
        if attrs.get('Content-Type'):
            cgienv['CONTENT_TYPE'] = attrs['Content-Type'][0]
        if attrs.get('Referer'):
            cgienv['HTTP_REFERER'] = attrs['Referer'][0]
        if attrs.get('Cookie'):
            cgienv['HTTP_COOKIE'] = attrs['Cookie'][0]

        # pprint.pprint(vars(conn))
        pprint.pprint(cgienv)

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

        if filename.endswith('.php'):
            os.execve('/usr/bin/php5-cgi', ['php5-cgi', filename], cgienv)
        else:
            os.execve(filename, (filename, ), cgienv)

        os.abort()
    else: # parent
        try:
            os.close(to_cgi_read_end)
            os.close(from_cgi_write_end)
            if conn.request.http_method == 'POST':
               # print 'post ' * 50 
               # print conn.body
               # print '#' * 30
               os.write(to_cgi_write_end, conn.request.body)
            response = ''
            isfirst = True
            while True:
                data = os.read(from_cgi_read_end, 4096)
                # print '+-' * 40
                # print data
                # print '+=' * 40
                if not data:
                    print 'return not data'
                    break
                response += data
            os.close(to_cgi_write_end)
            os.close(from_cgi_read_end)
            print '_+' * 20
        except:
            traceback.print_exc()

        # print '[response]' * 5
        # print response
        cgi_response_parse(conn, response)

    return 0 

def make_direct_reply(conn, http_status, msg, html):
    response = Response()
    response.response_type = Response.RESPONSE_FROM_MEM
    response.response = html
    response.headers['Content-Type'].append('text/html')
    response.headers['Content-Length'].append(str(len(html)))
    response.content_length = len(html)

    conn.http_status = http_status
    conn.response = response 

def handle_request(conn):
    filename = os.path.normpath(DOCUMENT_ROOT + conn.request.uri)

    print 'AB' * 50
    print filename

    # check whether the file exists
    if not os.path.isfile(filename):
        # try to add normal file to the end of uri
        for name in default_files:
            test_name = os.path.join(filename, name)
            if os.path.isfile(test_name):
                conn.request.uri = os.path.join(conn.request.uri, name)
                filename = test_name
                break
        else:
            make_direct_reply(conn, 404, 'Not Found',
                              '404 Not Found You Wanted')
            return

    ext = os.path.splitext(filename)[1]
    ext = ext[1:] if ext.startswith('.') else ext

    # check if there's special handler for this file
    # ...... 
    if ext in handlers.keys():
        handlers[ext](conn)
        return

    # ok, it's a normal static file
    # privilege
    try:
        f = open(filename, 'rb')
    except IOError, e:
        make_direct_reply(conn, 403, 'Forbidden',
                          'Permision Denied')
        return

    file_status = os.stat(filename) 
    file_size = file_status[stat.ST_SIZE]
    modified_date = file_status[stat.ST_MTIME]

    # static file
    conn.http_status = 200 

    response = Response()
    response.response_type = Response.RESPONSE_FROM_FILE
    response.response_fd = f
    response.content_length = file_size
    response.headers['Content-Type'].append(get_mime(ext))
    response.headers['Content-Length'].append(str(file_size))

    conn.response = response

def read_request(conn):
    data = conn.sockfd.recv(4096)
    header, header_end_pos = get_header(data)

    request = Request(header)

    if request.http_method == 'POST':
        weWant = int(request.content_length)
        weHad = len(data) - header_end_pos

        print 'weWant', weWant
        print 'weHad', weHad

        to_read = weWant - weHad

        body = data[header_end_pos:] 
        if to_read > 0:
            print 'fuck' * 411
            tail = conn.sockfd.recv(to_read)
            body += tail

        request.body = body 

    conn.request = request

    conn.keepalive = True if \
        request.headers.get('Connection', [''])[0].lower() == 'keep-alive' else False

def response_request(conn):
    r = conn.response
    print '[response_request]'
    # pprint.pprint(vars(r))
    # pprint.pprint(vars(conn))

    status_line = '%s %d %s\r\n' % (
        HTTP_PROTOCOL, conn.http_status, 'Fuck')
    headers = r.headers
    # headers = '\r\n'.join((': '.join((key, headers[key])) for key in headers))

    header_text = ''
    for key in headers:
        for v in headers[key]:
            header_text += ''.join((key, ': ', v, '\r\n'))
    header_text += '\r\n'

    print 'X' * 100
    print header_text

    conn.sockfd.send(status_line)
    conn.sockfd.send(header_text)
    # conn.sockfd.send('\r\n\r\n')

    if r.response_type == Response.RESPONSE_FROM_MEM:
        conn.sockfd.send(r.response)
    elif r.response_type == Response.RESPONSE_FROM_FILE:
        while True:
            data = r.response_fd.read(8192)
            if len(data) == 0: break
            conn.sockfd.send(data)
        r.response_fd.close()
        r.response_fd = -1

def handle_connection(conn):
    try:
        while True:
            conn.reset()

            read_request(conn)

            handle_request(conn)

            if conn.keepalive:
                conn.response.headers['Connection'].append('Keep-Alive')
                conn.response.headers['Keep-Alive'].append('timeout=%d' % (timeout, ))

            response_request(conn)

            if not conn.keepalive:
                break
    except socket.error:
        print '{socket.error connection die}'
    except Exception, e:
        traceback.print_exc()


if __name__ == '__main__':
    handlers = {
        'php': handle_php,
        'py': handle_cgi,
        }

    server = MultiThreadServer(host, port)
    server.serve_forver()
