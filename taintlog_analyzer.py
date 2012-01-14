################################################################################
# (c) 2011
# Author: Daniel Baeumges dbaeumges@googlemail.com
#
# This program is distributed WITHOUT ANY WARRANTY.
#
################################################################################

from optparse import OptionParser
from taintlog_json import *
from common import Logger, LogLevel

import re


# ================================================================================
# TaintLog Analyzer Error Obejct
# ================================================================================ 
class TaintLogAnalyzerError(Exception):  
    def __init__(self, theValue):
        self.value = theValue

    def __str__(self):
        return repr(self.value)


# ================================================================================
# Log Analyzer
# ================================================================================ 
class TaintLogAnalyzer:
    def __init__(self, theLogger=Logger()):
        self.log = theLogger

        self.jsonFactory = JsonFactory()
        
        self.logLines = []
        self.logEntryList = []
        self.json2pyFailedList = []
        self.json2pyFailedErrorList = []

        self.numControlChars = 0

    def setLogFile(self, theFile):
        """
        Sets the log lines from the provided file
        """
        logFile = open(theFile, 'r')
        for line in logFile:
            self.logLines.append(line)
        self.numControlChars = 2

    def setLogString(self, theStr):
        """
        Sets the log lines from the provided string splitted by \r\n
        """
        self.logLines = theStr.split('\r\n')
        self.numControlChars = 0

    def getLogEntryList(self, theType=None):
        """
        Returns the extracted log objects.
        extractLogObjects need to be run before.
        If theType is specified only entries of this instance are returned
        """
        if theType is None:
            return self.logEntryList
        else:
            logEntryList = []
            for logEntry in self.logEntryList:
                if isinstance(logEntry, theType):
                    logEntryList.append(logEntry)
            return logEntryList

    def getNumLogEntries(self, theType=None):
        """
        Return the number of log objects.
        extractLogObjects need to be run before.
        If theType is specified only entries of this instance are returned
        """
        if theType is None:
            return len(self.logEntryList)
        else:
            num = 0
            for logEntry in self.logEntryList:
                if isinstance(logEntry, theType):
                    num += 1
            return num
                
    def getJson2PyFailedList(self):
        """
        Returns the list of JSON strings which couldn't
        be converted into LogEntries.
        """
        return self.json2pyFailedList

    def getJson2PyFailedErrorList(self):
        """
        Returns the list of JSON strings which couldn't
        be converted into LogEntries inclduing the error
        """
        return self.json2pyFailedErrorList
        
    def extractLogEntries(self):
        """
        Extract JSON objects out of the log lines.
        setLogFile(<file>) or setLogString(<string>) need to be run before
        """
        # Init regex
        regexBegin = 'W\([ 0-9]{5}:0x[0-9a-f]*\) TaintLog: \['
        #regexBegin = 'W/dalvikvm\([ 0-9]{5}\): TaintLog: \['
        #regexGoOn = 'W/dalvikvm\([ 0-9]{5}\): '
        
        # Extract JSON strings
        self.log.info('Extract JSON string lines')
        jsonStringVec = []

        jsonStringDict = {}
        for line in self.logLines:
            # Extract PID and TID
            startPidTidPos = line.find('(')
            endPidTidPos = line.find(')')
            pidTid = line[startPidTidPos+1:endPidTidPos]

            #print 'line: "%s", pidTid: "%s"' % (line, pidTid)
            
            # Check for entry
            if not jsonStringDict.has_key(pidTid):
                regexMatch = re.match(regexBegin, line)
                if not regexMatch is None:
                    #print "FOUND regex"
                    
                    # Check for end in same line
                    if line[len(line)-1] == ']' or line[len(line)-2] == ']' or line[len(line)-3] == ']':
                        jsonString = line[regexMatch.end()-1:len(line)]
                        jsonStringVec.append(jsonString)
                        self.log.debug('Found JSON string: \'%s\'\n' % jsonString)
                    else:
                        jsonString = line[regexMatch.end()-1:len(line)-self.numControlChars] # remove control chars at the end
                        jsonStringDict[pidTid] = jsonString

            else: # pidTid found
                regexGoOn = 'W\(%s\) ' % pidTid
                #print 'regex: %s' % regexGoOn
                regexMatch = re.match(regexGoOn, line)
                if not regexMatch is None:
                    partString = line[regexMatch.end():len(line)-self.numControlChars] # remove control chars at the end
                    jsonStringDict[pidTid] += partString
                    if line[len(line)-1] == ']' or line[len(line)-2] == ']' or line[len(line)-3] == ']':                        
                        jsonStringVec.append(jsonStringDict[pidTid])                    
                        self.log.debug('Found JSON string: \'%s\'\n' % jsonStringDict[pidTid])
                        del jsonStringDict[pidTid]
                else:
                    self.log.info('Warning: Do not find line match even though it was expected\n')

        # Extract JSON objects
        self.logEntryList = []
        self.json2pyFailedList = []
        self.json2pyFailedErrorList = []
        self.log.info('Extract JSON objects')
        for jsonString in jsonStringVec:
            self.log.dev(jsonString)
            try:
                self.logEntryList.extend(self.jsonFactory.json2Py(jsonString))
            except Exception, ex:
                self.json2pyFailedList.append(jsonString)
                errMsg = 'Conversion for JSON string \'%s\' failed: %s.' % (jsonString, str(ex))
                self.log.error(errMsg)
                self.json2pyFailedErrorList.append(errMsg)

    def postProcessLogObjects(self, theDeleteStaleObjectsFlag=True):
        """
        CleanUp log objects:
        - Generate stack trace vector
        - Set file path for OSFileAccess
        """
        cipherUsageDict = {}

        filteredLogEntryList = []
        logEntryIndex = 0
        for logEntry in self.logEntryList:
            # Stack trace vec
            if isinstance(logEntry, CallActionLogEntry) or \
               isinstance(logEntry, CipherUsageLogEntry) or \
               isinstance(logEntry, ErrorLogEntry) or \
               isinstance(logEntry, FileSystemLogEntry) or \
               isinstance(logEntry, NetworkSendLogEntry) or \
               isinstance(logEntry, SSLLogEntry) or \
               isinstance(logEntry, SendSmsLogEntry):
                stackTrace = logEntry.stackTraceStr.split('||')
                logEntry.stackTrace = stackTrace[:len(stackTrace)-1]

            # Filter log entry?
            if self.__removeLogObjectByFilter(logEntry):
                filteredLogEntryList.append(logEntryIndex)
                
            # Cipher cleaning (combine inputs and outputs)
            if isinstance(logEntry, CipherUsageLogEntry):
                if logEntry.action == CipherActionEnum.INIT_ACTION:
                    if cipherUsageDict.has_key(logEntry.id):
                        cipherUsageDict[logEntry.id][0].tag = TaintTagEnum.appendTaintTags(cipherUsageDict[logEntry.id][0].tag, logEntry.tag)
                        cipherUsageDict[logEntry.id][0].input = logEntry.input + cipherUsageDict[logEntry.id][0].input
                        cipherUsageDict[logEntry.id][0].output = logEntry.output + cipherUsageDict[logEntry.id][0].output
                        cipherUsageDict[logEntry.id][1].append(logEntryIndex)               
                    else:
                        cipherUsageLogEntry = CipherUsageLogEntry(action=CipherActionEnum.CLEANED,
                                                                  id=logEntry.id,
                                                                  mode=logEntry.mode,
                                                                  tag=logEntry.tag,
                                                                  input='',
                                                                  output='',
                                                                  stackTraceStr=logEntry.stackTraceStr,
                                                                  stackTrace=logEntry.stackTrace,
                                                                  timestamp=logEntry.timestamp)
                        cipherUsageDict[logEntry.id] = [cipherUsageLogEntry, [logEntryIndex]]
                        
                else: # logEntry.action != CipherActionEnum.INIT_ACTION
                    if cipherUsageDict.has_key(logEntry.id):
                        cipherUsageDict[logEntry.id][0].tag = TaintTagEnum.appendTaintTags(cipherUsageDict[logEntry.id][0].tag, logEntry.tag)
                        cipherUsageDict[logEntry.id][0].input += logEntry.input
                        cipherUsageDict[logEntry.id][0].output += logEntry.output
                        cipherUsageDict[logEntry.id][1].append(logEntryIndex)
                        
                    else:
                        cipherUsageLogEntry = CipherUsageLogEntry(action=CipherActionEnum.CLEANED,
                                                                  id=logEntry.id,
                                                                  mode=logEntry.mode,
                                                                  tag=logEntry.tag,
                                                                  input='',
                                                                  output='',
                                                                  stackTraceStr=logEntry.stackTraceStr,
                                                                  stackTrace=logEntry.stackTrace,
                                                                  timestamp=logEntry.timestamp)
                        cipherUsageDict[logEntry.id] = [cipherUsageLogEntry, [logEntryIndex]]
                        self.log.info("CipherUsageLogEntry with action '%s' found without starting init" % logEntry.action)
                
            # Update index
            logEntryIndex += 1

        # Delete stale objects
        if theDeleteStaleObjectsFlag:
            # Collect indices
            delLogEntryIdxList = []
            
            # Cipher usage
            for id, logEntry in cipherUsageDict.iteritems():
                delLogEntryIdxList.extend(logEntry[1])

            # Do drop
            delLogEntryIdxList.sort()
            for i in xrange(len(delLogEntryIdxList)):
                del self.logEntryList[delLogEntryIdxList[i] - i]
            

        # Add cleaned cipher usage objects
        for id, logEntry in cipherUsageDict.iteritems():
            self.logEntryList.append(logEntry[0])


    def __removeLogObjectByFilter(self, theLogObject):
        """
        Returns if log object should be filtered.
        """
        return False
            

    def printOverview(self):
        """
        Print overview.
        FileDescriptorObjects need to be deleted before
        """
        for logEntry in self.logEntryList:
            self.log.write(logEntry.getOverviewLogStr())


# ================================================================================
# Main method
# ================================================================================
def main():
    # Parse options
    parser = OptionParser(usage='usage: %prog [options] logcatFile', version='%prog 0.1')    
    parser.add_option('-v', '--verbose', action='store_true', dest='verbose', default=True)
    parser.add_option('-q', '--quiet', action='store_false', dest='verbose')
    (options, args) = parser.parse_args()

    # Run
    if options.verbose:
        logger = Logger(LogLevel.DEBUG)
    else:
        logger = Logger()
    logAnalyzer = TaintLogAnalyzer(theLogger=logger)
    logAnalyzer.setLogFile(args[0])
    logAnalyzer.extractLogEntries()
    logAnalyzer.postProcessLogObjects()
    logAnalyzer.printOverview()

if __name__ == '__main__':
    main()
    
