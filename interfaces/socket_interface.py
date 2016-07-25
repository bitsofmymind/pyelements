# socket_interface.py - A class for interfacing with an elements framework on a port
# Copyright (C) 2016 Antoine Mercier-Linteau
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Note: it's possible to debug the c++ called from python using 
# gdb /usr/bin/python server.py

import socket
import errno
from elements.core import Resource, Request, Response, get_uptime
from threading import Thread

class SocketInterface(Resource):
    """ A resource for interfacing with a tcpip socket. """
    
    class SocketListener(Thread):
        """ A thread for listening for incoming connections on sockets. """
        
        def __init__(self, ip, port, interface):
            """ Initialize the object.
            
            ip -- the address of the interface to listen on.
            port -- the port to listen to.
            interface -- the interface object that owns this listener.
            """
            
            Thread.__init__(self)
            self.ip = ip
            self.port = port
            self.interface = interface
            self._closed = False # This is set to true to terminate the thread.
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.setblocking(1)
            self._socket.bind((ip, port))
            self._socket.listen(5)
            
            Thread.start(self)
        
        def close(self):
            """ Terminate thread and close the listener's socket."""
            
            self._closed = True # Terminate the thread.
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect( (self.ip, self.port))
            self._socket.close()
        
        def run(self):
            """ Listen for incoming connections. """
            
            while(not self._closed):
                
                connection, client_address = self._socket.accept()
                
                # If a bogus connection to the socket was used to terminate the thread.
                if(self._closed):
                    break 
                
                print ' > connection from', client_address
                
                # Add a new request to the queue.
                self.interface.connections[client_address] = {
                    'connection' : connection,
                    'state': 'accepted',
                    'last_used': get_uptime()
                }
                
                self.interface.schedule(0) # Schedule the interface to process the new request.
    
    def __init__(self, ip, port):
        """ Initialize the resource.
        
        ip -- the ip of the interface to listen on.
        port -- the port to listen on.
        """
        
        Resource.__init__(self)
        
        self.connections = {} # The connection queue.
        # Create a listener for the given interface.
        self.listeners = {(ip, port): self.SocketListener(ip, int(port), self)}
    
    def __del__(self):
        self.close()
    
    def close(self):
        """ Close the interface. """
        
        print '*** Closing interface ...'
        
        for connection in self.connections.items():
            print ' > closing connection on ' + connection[0][0] + ':' + str(connection[0][1]) + ' ... ',
            connection['connection'].close()
            print '(done)'
        
        for listener in self.listeners.items():
            print ' > closing listener on ' + listener[1].ip + ':' + str(listener[1].port) + ' ... ',
            listener[1].close()
            listener[1].join() # Wait for the thread to exit.
            print '(done)'
        
        print '*** Done closing interface'
    
    def run(self):
        """ Processes all connections."""
        
        connections_to_close = []
        
        for key in list(self.connections):
            
            client_address = key
            connection = self.connections[key]
            
            if(connection['state'] == 'accepted'):
                # A connection has just been accepted.
                message = ''
                
                while(True):
                    try:
                        # Receive data from the connection.
                        data = connection['connection'].recv(1024, socket.MSG_DONTWAIT)
                        connection['last_used'] = get_uptime()
                        message += data
                        # If less bytes that expected have been received, this 
                        # means that we have received all the data.
                        if(len(data) < 1024):
                            break
                        
                    except Exception as e:
                        # If the socket would block waiting for more data.
                        if(e.errno == errno.EWOULDBLOCK):
                            break # Done retrieving all data from the socket.
                        else: # Unexpected error.
                            connections_to_close.append(client_address)
                            raise e
                            
                if(not message): # If the connection yielded no data.
                    # If the connection has not been used for 10 seconds.
                    if(get_uptime() - connection['last_used'] >= 10000):
                        connections_to_close.append(client_address)
                    else:
                        self.schedule(10) # Check later if some data has arrived.
                    continue
                
                if(not connection.has_key('request')):
                    connection['request'] = Request()
                
                request = connection['request'];
                
                result = request.parse(message) # Parse the data into a request.
                
                if(result == Request.PARSING_SUCESSFUL): 
                    continue # Wait for more data.
                elif(result != Request.PARSING_COMPLETE):
                    # The request was invalid.
                    connections_to_close.append(client_address)
                    continue
                
                print ' > dispatching request from ', client_address, 'to ',
                request.get_to_url()._print()
                print ''
                
                connection['state'] = 'dispatched'
                
                # Appends the source ip and port to the from url to they can
                # be retrieved when the message comes back.
                request.get_from_url().append_resource(str(client_address[0]))
                request.get_from_url().append_resource(str(client_address[1]))
                
                request.__disown__() # Hand over the request to C++.
                
                self.dispatch(request) # Dispatch the message to its destination.
            elif(connection['state'] == 'responded'): # A request has been responded to.
                print ' > sending response to', client_address
                
                # Serialize the response and send it over to the connection.
                data = connection['response'].serialize()
                connection['connection'].sendall(data)
                connections_to_close.append(client_address)
                
        # Close connections that have been processed or were invalid.
        for address in connections_to_close:
            self.connections[address]['connection'].close()
            del self.connections[address]
            print ' > closing', address
            
    def process_response(self, response):
        """ Process a response
        
        response -- the response object.
        """
        
        # Any response that ends up here is assumed to be directed towards the interface.
        response.next() # Next resource on the url should be the ip.
        ip = response.current()
        response.next() # Next resource on the url should be the port.
        port = int(response.current())
        
        print ' > got response from ', 
        response.get_from_url()._print()
        print 'for', (ip, port)
        
        # If this ip/port tuple was not a connection that was opened though this interface.
        if (ip, port) not in self.connections:
            print ' > unknown response for', (ip, port)
            # This response ended up here for unknown reasons, disown it because
            # returning a DONE_207 will cause the framework to delete the object
            # in C++.
            response.__disown__()
            return Response.DONE_207
        
        # A response to a previous request has arrived so schedule a reply.
        self.connections[(ip, port)]['response'] = response
        self.connections[(ip, port)]['state'] = 'responded'    
        self.schedule(0)
        
        # Indicate that we are keeping the message within our control.
        return Response.RESPONSE_DELAYED_102
        