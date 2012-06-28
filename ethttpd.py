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
timeout = 15
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

class Request(object):
    def __init__(self, header):
        self.request = ''
        self.uri = ''
        self.orig_uri = ''
        self.http_method = ''
        self.http_version = ''
        self.request_line = ''
        self.headers = {}
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
            self.query_string = qpos[qpos + 1:]
            self.uri = qpos[:qpos]
        
        self.http_method = method
        self.http_version = protocol 

        for i in range(1, len(lines)):
            key, value = lines[i].split(': ')
            self.headers[key] = value

        self.content_length = self.headers.get('Content-Length', -1) 

class Response(object):
    RESPONSE_FROM_FILE = 0
    RESPONSE_FROM_MEM = 1

    def __init__(self):
        self.content_length = -1
        self.keepalive = False
        self.headers = {}
        self.response_type = Response.RESPONSE_FROM_MEM
        self.response = ''
        self.response_fd = -1 
        
class Connection(object):
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
        cgienv['HTTP_CONNECTION'] = 'Keep-Alive' if conn.keepalive else 'close'
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

def make_direct_reply(conn, http_status, msg, html):
    response = Response()
    response.response_type = Response.RESPONSE_FROM_MEM
    response.response = html
    response.headers['Content-Type'] = 'text/html'
    response.headers['Content-Length'] = str(len(html))

    conn.http_status = http_status
    conn.response = response 

def handle_request(conn):
    uri = os.path.normpath(DOCUMENT_ROOT + conn.request.uri)

    print uri

    # check whether the file exists
    if not os.path.isfile(uri):
        # try to add normal file to the end of uri
        for name in ('index.php',):
            pass
        make_direct_reply(conn, 404, 'Not Found',
                          '404 Not Found You Wanted')
        return

    # check if there's special handler for this file
    # ...... 
    if 0:
        return

    # ok, it's a normal static file
    # privilege
    try:
        f = open(uri, 'rb')
    except IOError, e:
        make_direct_reply(conn, 403, 'Forbidden',
                          'Permision Denied')
        return

    file_status = os.stat(uri) 
    file_size = file_status[stat.ST_SIZE]
    modified_date = file_status[stat.ST_MTIME]

    # static file
    conn.http_status = 200

    ext = os.path.splitext(uri)[1]
    ext = ext[1:] if ext.startswith('.') else ext

    response = Response()
    response.response_type = Response.RESPONSE_FROM_FILE
    response.response_fd = f
    response.content_length = file_size
    response.headers['Content-Type'] = get_mime(ext)
    response.headers['Content-Length'] = str(file_size)

    conn.response = response

def read_request(conn):
    data = conn.sockfd.recv(4096)
    header, header_end_pos = get_header(data)

    request = Request(header)

    if request.http_method == 'POST':
        weWant = request.content_length
        weHad = len(data) - header_end_pos
        body = conn.sockfd.recv(weWant - weHad)
        body = data[header_end_pos:] + body
        request.body = body 

    conn.request = request

    conn.keepalive = True if \
        request.headers.get('Connection', '').lower() == 'keep-alive' else False

def response_request(conn):
    r = conn.response

    status_line = '%s %d %s\r\n' % (
        HTTP_PROTOCOL, conn.http_status, 'OK')
    headers = r.headers
    headers = '\r\n'.join((': '.join((key, headers[key])) for key in headers))

    conn.sockfd.send(status_line)
    conn.sockfd.send(headers)
    conn.sockfd.send('\r\n\r\n')

    if r.response_type == Response.RESPONSE_FROM_MEM:
        conn.sockfd.send(r.response)
    elif r.response_type == Response.RESPONSE_FROM_FILE:
        while True:
            data = r.response_fd.read(8192)
            if len(data) == 0: break
            conn.sockfd.send(data)
        r.response_fd.close()

def handle_connection(conn):
    try:
        while True:
            conn.reset()

            read_request(conn)

            handle_request(conn)

            if conn.keepalive:
                conn.response.headers['Connection'] = 'Keep-Alive' 
                conn.response.headers['Keep-Alive'] = 'timeout=%d' % (timeout, )

            response_request(conn)

            if not conn.keepalive:
                break
    except socket.error:
        print '{socket.error connection die}'
    except Exception, e:
        traceback.print_exc()


if __name__ == '__main__':
    server = MultiThreadServer(host, port)
    server.serve_forver()
