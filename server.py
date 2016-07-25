# server.py - A server for interfacing with the elements framework
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

from elements import core
from elements import pal
from interfaces import socket_interface
import time
import signal
import threading
import sys

processing_condition = threading.Condition()

# Define functions needed by the framework.

def init():
    """ Initialize framework functions. """
    
    pass

def terminate():
    """ Terminate the framework. """
    
    pass

def processing_wake(): 
    """ Wake the framework from sleep. """
    
    processing_condition.acquire()
    processing_condition.notifyAll()
    processing_condition.release()
    pass
    
def processing_sleep(msecs):
    """ Make the framework sleep. 
    
    msecs -- time to sleep in milliseconds.
    """    
    
    if(msecs == 0): return
    
    processing_condition.acquire()
    
    if(msecs < 0): # If we are supposed to sleep until an interrupt comes.
        msecs = 10000000000 
    
    processing_condition.wait(msecs / 1000)
    processing_condition.release()
    
def heart_beat():
    """ This function is called when the framework has gone though a cycle. """
    
    pass

class UptimeThread(threading.Thread):
    """ A thread for keeping the framework's uptime. """
    
    def __init__(self):
        threading.Thread.__init__(self)
        self.stopped = False # Set this to false to stop the thread.
      
    def run(self):
        """ Run the thread. """
        
        while(not self.stopped):
            pal.increase_uptime(1)
            time.sleep(0.001)

if len(sys.argv) < 3:
    print 'Missing ip and/or port arguments.'
    sys.exit(1)

def sigint_handler(signum, frame):
    print '(received SIGNINT)'
    t.stopped = True
    t.join()
    socket.close()
    sys.exit(0)

signal.signal(signal.SIGINT, sigint_handler)

t = UptimeThread()
t.start()

socket = None

print '*** Setting up resources ...'
try:
    print ' > root ... ',
    root = core.Resource()
    print '(done)'
    
    print ' > processing ... ',
    processing = core.Processing()
    processing.__disown__() # Let C++ handle this object since it belongs to root.
    root.add_child('processing', processing)
    print '(done)'
    
    print ' > socket ... ',
    socket = socket_interface.SocketInterface(sys.argv[1], sys.argv[2])
    #socket.__disown__() # Let C++ handle this object since it belongs to root.
    root.add_child('socket', socket)
    print '(done)'
except Exception as e:
    # Something went wrong, terminate the program.
    print '(failed)'
    t.stopped = True
    t.join()
    if socket != None: socket.close()
    raise e
    
print '*** Done setting up resources'

print '*** Running server ...'
try:
    processing.start() # Will not return.
except KeyboardInterrupt:
    sigint_handler(0, 0)
