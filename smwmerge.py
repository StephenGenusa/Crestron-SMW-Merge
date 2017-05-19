#!/usr/bin/env python

import difflib
import sys
import tkMessageBox
import re
import logging

from optparse import OptionParser

newline = '\r\n'

program_description = """
Perform a three-way merge on a SIMPL Windows file.
Given a base file (original-file), changes that you've made to that file (your-file)
and changes someone else has made to that file (their-file), both your changes
and their changes will be merged into a final output.
"""

copyright = """
Copyright Ian Epperson.  Parts based on a file called mymerge.py written by Marcos Chaves.

This software may be used and distributed according to the terms
of the GNU General Public License, incorporated herein by reference.
"""

version = "0.1"

LOGGING_LEVELS = {'critical': logging.CRITICAL,
                  'error': logging.ERROR,
                  'warning': logging.WARNING,
                  'info': logging.INFO,
                  'debug': logging.DEBUG}


class redict(dict):
	'''A dictionary enhancement where missing keys are looked up in a seperate dict'''
	def setBase(self, base):
		self.base = base
		
	def __missing__(self, key):
		try:
			return self.base[key]
		except KeyError:
			raise KeyError(key)

########################################################
##
##   Merge classes and objects
##
########################################################
	
class Merge:
	class marker:
		add    = '+ '
		remove = '- '
		inline = '? '
		same   = '  '
	differ = difflib.Differ()
	
	def __init__(self, a=False, b=False, x=False):
		self.ran = False
		if a<>False and b<>False and x<>False:
			self.conflict, self.result = self.threeWay(a,b,x)
			self.ran = True
			
		elif a<>False and b<>False:
			self.conflict = False
			self.result = self.twoWay(a,b)
			self.ran = True
		
		else:
			self.conflict = False
			self.result = []
			
	def __repr__(self):
		return self.result.__repr__()
		
	def __iter__(self):
		return self.result.__iter__()
	
	def __len__(self):
		return self.result.__len__()
		
	def __getitem__(self, item):
		return self.result.__getitem__(item)
	
	def eliminateInlineMarkers( self, list ):
		'''Remove any inline markers from the given list.
		   Note that this will modify the given list'''
		#Step backwards through the list so removed items will not munge up the position
		for ref in range( len(list)-1, 0, -1 ):
			if list[ref].startswith( self.marker.inline ):
				del list[ref]
	
	#merge two lists, keeping all elements of each in order
	def twoWay(self,a,b, a_name='A', b_name='B'):
		#return [r[2:] for r in self.differ.compare(a,b)]
		m = []
		status = ''
		for item in self.differ.compare(a,b):
			status = item[:2]
			text = item[2:]
			if status == self.marker.inline:
				continue
			
			if status == self.marker.same:
				m.append( text )
				continue
				
			#in a but not in b
			if status == self.marker.remove:
				m.append( self._preprocessAdd( text, a_name ) )
				continue
				
			#in b but not in a
			if status == self.marker.add:
				m.append( self._preprocessAdd( text, b_name ) )
				continue
		
		return m

	#perform a three-way merge using _conflictManger for any conflicts
	def threeWay(self, a, b, x, a_name = 'A', b_name = 'B'):
		xa = list( self.differ.compare(x, a) )
		xb = list( self.differ.compare(x, b) )
		m = []
		index_a = 0
		index_b = 0
		had_conflict = False
		status_a = ''
		status_b = ''
		ca = []
		cb = []
		cm = []
		lastStatus = ('','')
		
		self.eliminateInlineMarkers( xa )
		self.eliminateInlineMarkers( xb )
		
		self.a = a
		self.b = b
		self.x = x
		self.xa = xa
		self.xb = xb
		
		while ( index_a < len(xa) ) and ( index_b < len(xb) ):
			lastStatus = status_a, status_b
			status_a = xa[index_a][:2]
			status_b = xb[index_b][:2]
			
			# no changes or identical adds on both sides
			if xa[index_a] == xb[index_b]:
				if status_a == self.marker.same:
					m.append( xa[index_a][2:] )
					index_a += 1
					index_b += 1
					continue
				elif status_a == self.marker.add:
					m.append( self._preprocessAdd(xa[index_a][2:], a_name ) )
					index_a += 1
					index_b += 1
					continue

			# removing matching lines from one or both sides
			if ( (xa[index_a][2:] == xb[index_b][2:])
				and ( status_a == self.marker.remove or status_b == self.marker.remove ) ):
				index_a += 1
				index_b += 1
				continue

			# adding lines in A
			if status_a == self.marker.add and status_b == self.marker.same:
				m.append( self._preprocessAdd(xa[index_a][2:], a_name ) )
				index_a += 1
				continue

			# adding line in B
			if status_b == self.marker.add and status_a == self.marker.same:
				m.append( self._preprocessAdd(xb[index_b][2:], b_name ) ) 
				index_b += 1
				continue
			
			# At this point, the only remaining possiblity is an add from both sides that doesn't match
			
			# possible conflict.  Attempt last ditch merge
			mergedLine = self._lastDitchMerge( xa[index_a][2:], xb[index_b][2:] )
			if mergedLine:
				m.append( mergedLine )
				index_a += 1
				index_b += 1
				continue
			
			# conflict - build list of conflicting lines and pass to handler
			ca = []
			cb = []
			#build list of conflicting lines from A
			while (index_a < len(xa)) and not xa[index_a].startswith( self.marker.same ):
				ca.append( self._preprocessAdd(xa[index_a][2:], a_name) )
				index_a += 1
			#build list of conflicting lines from B
			while (index_b < len(xb)) and not xb[index_b].startswith( self.marker.same ):
				cb.append( self._preprocessAdd(xb[index_b][2:], b_name) )
				index_b += 1
				
			#pass lists to conflict manager
			resolved, cm = self._conflictManager(ca, cb, lastStatus)
			m.extend(cm)
			if not resolved:
				had_conflict = True

		# append remining lines - there will be only either A or B
		for i in range(len(xa) - index_a):
			m.append( self._preprocessAdd( xa[index_a + i][2:], a_name ) )
		for i in range(len(xb) - index_b):
			m.append( self._preprocessAdd( xb[index_b + i][2:], b_name ) )

		return had_conflict, m
	
	#perform a last attempt to merge the line before calling the conflict manager (stub)
	def _lastDitchMerge(self, element_a, element_b):
		return False
	
	#preprocess an element before adding it to the final entity (stub)
	def _preprocessAdd(self, element, sourceName):
		return element
	
	#conflictManagers take the a and b arrays as well as the last status
	#return an indication if the conflict was resolved (bool) and 
	#an array to be inserted into the result
	def _conflictManager(self, a, b, lastStatus):
		'''Show conflicts similar to GNU's diff3'''
		m = ["<<<<<<< A\n"]
		m.extend(a)
		m.append("=======\n")
		m.extend(b)
		m.append(">>>>>>> B\n")
		return False, m

class MergeConservative( Merge ):
	def _conflictManager(self, a, b, lastStatus):
		'''Only return the other files' changes during conflict'''
		return True, b

class MergeGreedy( Merge ):
	def _conflictManager(self, a, b, lastStatus):
		'''Return the sum of all a and b.'''
		m = []
		m.extend(a)
		m.extend(b)
		return True, m


#used for mulitple inheretance	
class SMWMerger():
	hRefFinder = re.compile( '^([^=]{0,3}H)=', re.M )
	childFinder = re.compile( '^(C[0-9]{1,4})=', re.M )
	def _preprocessAdd(self, element, sourceName):
		'''Find any H= references and convert to H(side)='''
		result = element
		result = self.hRefFinder.sub( r'\1-' + sourceName + '=', result )
		result = self.childFinder.sub( r'\1-' + sourceName + '=', result )
		return result
		
	def _lastDitchMerge(self, element_a, element_b):
		# try a line-by-line merge and verify the result is still a legal SMW object		
		result = newline.join( self.twoWay( element_a.split(newline), element_b.split(newline) ) )
		try:
			smwObject(result)
			return result
		except SMWError:
			return False
		

class SMWMergeConservative( SMWMerger, MergeConservative ):
	pass

class SMWMergeGreedy( SMWMerger, MergeGreedy ):
	pass

class MergeMaxKeys( Merge ):
	def _lastDitchMerge(self, element_a, element_b):
		# perform a line-by-line merge and keep the highest value keys
		# will always return a completed result
		result = self.twoWay( element_a.split(newline), element_b.split(newline) )
		final = []
		
		last = ('', '')
		for line in result:
			current = result[line].split('=',1)
			if current[0] == last[0]:
				if current[1] > last[1]:
					final[-1] = current
				else:
					pass
			else:
				final.append( result[line] )
				
			last = current
		
		return newline.join(final)
		
	def _conflictManager(self, a, b, lastStatus):
		#should never ever reach this
		raise NotImplementedError('MergeMaxKeys somehow fell to the Conflict Manager.')
		
class MergeSymbols( SMWMerger, Merge ):
	def _conflictManager(self, a, b, lastStatus):
		logging.debug( 'at MergeSymbols._conflictManager\n - len(a)=' + str(len(a)) + ' len(b)=' + str(len(b)) )
		logging.debug(' - lastStatus='+str(lastStatus) )
		
		# if we had not just removed a symbol in each file, add both greedily
		if ( lastStatus <> (self.marker.remove, self.marker.remove) ):
			return True, a + b

		logging.debug( 'a list:\n')
		for ai in a:
			logging.debug( ai )
			
		logging.debug( '\n\nb list:\n' )
		for bi in b:
			logging.debug( bi )

			
		tkMessageBox.showerror("SMW Merge Error", "Unhandled merge conflict in the symbol library.\n\nResulting program will be incomplete.")
		# TODO! check if there's a folder.  If it is, add comment with one of the folder names and use the other
		# if not, create conflict folder
		return True, []
		

class Order:
	def __init__(self):
		self.differ = difflib.Differ()
		self._list = []
		
	#general function to merge two lists, keeping all elements of each in order
	def cat(self,a,b):
		return [r[2:] for r in self.differ.compare(a,b)]

	#integrate the given list with the current
	def integrate(self, a):
		self._list = self.cat(self._list, a)
		
	def __len__(self):
		return len(self._list)
		
	#iter functions for easy list iteration
	def __iter__(self):
		return self._list.__iter__()

	def __repr__(self):
		return self._list.__repr__()


########################################################
##
##   SMW classes and objects
##
########################################################

		
masterObjOrder = Order()



class SMWError(Exception):
	pass


class smw:
	class type:
		symbol   = 'Sm'
		signal   = 'Sg'
		progInfo = 'FSgntr'
		header   = 'Hd'
		FP       = 'FP'
		BK       = 'Bk'
		openSm   = 'Bw'
		device   = 'Dv'
		Cm       = 'Cm'	#Cresnet Config?
		Db       = 'Db' #Central controller?
		
	class key:
		type     = 'ObjTp'
		name     = 'Nm'
		comment1 = 'Cmn1'
		parent   = 'PrH'
		child    = 'C0H'  #our special key
		ref      = 'H'
		refA     = 'H-A'  #our special key
		refB     = 'H-B'  #our special key
		symType  = 'SmC'
		symComplete = 'CF'  #1=symbol incomplete and shows *!*, 2=symbol complete
		childCount = 'mC'
		SmCrossRef = 'SmH'
		CmCrossRef = 'CmH'
		DbCrossRef = 'DbH'
	
	crossref = {
		#'PrH': current table
		key.SmCrossRef: type.symbol,
		key.CmCrossRef: type.Cm,
		key.DbCrossRef: type.Db,
		}
		
	
	class symType:
		folder  = '156'
		
	merge = {
		''            : MergeConservative,
		type.symbol   : MergeSymbols,
		type.signal   : SMWMergeGreedy,
		type.progInfo : MergeMaxKeys,
		type.header   : SMWMergeConservative,
		type.FP       : SMWMergeConservative,
		type.BK       : SMWMergeConservative,
		type.openSm   : False,				#do not try and merge any open symbols - not worth the effort
		type.Cm       : SMWMergeConservative,
		type.Db       : SMWMergeConservative,
		type.device   : SMWMergeConservative,
                'unknown'     : SMWMergeConservative,
		}

class smwObject:
	'''Creates a Python object from a single SMW object'''
	def __init__(self, string):
		#Store the original string
		self.baseString = string
		
		self.hidden = False
		
		#Store our references
		#self.references = references
				
		#Create a dictonary to hold all the key-value pairs
		self._data = {}
		self._dataOrder = []
		self.children = []
		#extract the key-value pairs
		_lines = string.split(newline)
		for _line in _lines:
			try:
				_key, _value = _line.split('=',1)
				self.newKey( _key, _value)
			except ValueError:
				pass
				#print('skipping line: '+self._line)
		
		
		#Determine the name for this object
		#Nm should contain the name
		if self.hasKey(smw.key.name):
			self.name = self.getKey(smw.key.name)
			
		#Subsystem (folder) objects have the name Cmn1
		else:
			self.name = self.getKey(smw.key.comment1)
		
		self.type = self.getKey(smw.key.type)
		
		self.SmC = self.getKey(smw.key.symType)
		
		try:
			self.parent = int( self.getKey(smw.key.parent) )
		except ValueError:
			self.parent = 0
		
		self.H = self.getKey(smw.key.ref)
		self.HA = self.getKey(smw.key.refA)
		self.HB = self.getKey(smw.key.refB)
		
		self.refs = {'':self.H, 'A':self.HA, 'B':self.HB}
		
		self.isParent = False
		
		# convert child keys to remove specific order number, except for devices which require specific H references
		if self.hasKey( smw.key.childCount ) and not ( self.type == smw.type.device ):
			self.convertChildRefs()
	
	def convertChildRefs(self):
		self.isParent = True
		self.setKey( smw.key.childCount, 'n' )  #count of children, just set to 'n'
			
		#C1 = first child, C2 = second, etc.  Change them all to our special child key
		count = 0
		while(1):
			count = count + 1
			try:
				key = 'C' + str(count) 
				keyObj = self._data[key]
				keyObj.key = smw.key.child
				self.children.append( keyObj )
			except:
				break
		
	
	class _key:
		def __init__(self, key, value):
			try:
				self.key, self.source = key.split('-')
				#print 'key source: ' + self.source
			except ValueError:
				self.source = ''
				self.key = key
			self.value = str(value)
			
		def __str__(self):
			return str(self.value)
		def __repr__(self):
			return str(self.value)
		def __int__(self):
			try:
				return int(self.value)
			except ValueError:
				return 0
		def render(self):
			return self.key + '=' + self.value
		
	def newKey(self, key, value):
		'''add a new key value pair, returning an error if there's a conflict'''
		newKey = self._key(key, value)
		
		#turn our special child key back into a proper SMW child key reference
		if newKey.key == smw.key.child:
			self.children.append(newKey)
			newKey.key = 'C' + str( len(self.children) )
			
		#Some keys may reference different lists (PrH-A and PrH-B) but tha A and B sides will conflict.
		#The only exception is the H (ref) key which defines this object in the A and B list.
		#The _key object will store the true key
		if newKey.key == smw.key.ref:
			refKey = key
		else:
			refKey = newKey.key
			
		if self._data.has_key(refKey) and str(self._data[refKey]) <> value:
			raise SMWError( "Duplicate conflicting key-value in SMW Object input.  Key=" + str(key) )
		else:
			self._data[refKey] = newKey
			
		if not newKey.key in self._dataOrder:
			self._dataOrder.append(newKey.key)
		
	def setKey(self, key, value):
		'''sets a given key to a given value and updates the dataOrder array as necessary'''
		try:
			self._data[ key ].value = str(value)
		except KeyError:
			raise SMWError( "Key not defined in SMW Object, but attempt was made to set it.  Key=" + str(key) )
	
	def getKey(self, key):
		try:
			return str(self._data[key])
		except:
			return ''	

	def getKeySource(self, key):
		return self._data[key].source
	
	def hasKey(self, key):
		return self._data.has_key(key)
	
	def delKey(self, key):
		try:
			del self._data[key]
		except:
			pass
	
	def setRef(self, value):
		'''Set this object's reference.  Does not modify the .refs dict.'''
		try:
			self.setKey( smw.key.ref, str(value) )
		except SMWError:
			self.newKey( smw.key.ref, str(value) )
		
		self.H = str(value)
	
	def fixSignals(self, signalTable):
		'''Turn all inputs and outputs from H references to signal names for easier diff'''
		if self.type == smw.type.symbol:
			#inputCount = int(self.data['mI'])
			for key in self._data:
				try:
					#find valid I5 or O10 kind of keys
					c = int(key[1:])
				except:
					c = False
				
				if c:
					#if this is an input or output (I# or O#)
					if key[:1] in ['I', 'O']:
						#replace the ref value with name from signal table
						sigRef = self.getKey( key )
						#sigName = self.references[smw.type.signal][sigRef].name
						sigName = signalTable[sigRef].name
						self.setKey( key, sigName )
#			 			try:
# 							self.setKey( key, self.references[smw.type.signal][int(self.data[key])].name )
# 						except KeyError:
# 							raise KeyError('Error.  Could not locate signal '+ str(self.data[key]) +' - SMW file corrupt' )
		
	def __str__(self):
		out = ['[']
		
		
		for key in self._dataOrder:
			try:
				out.append( self._data[key].render() )
			except KeyError:
				pass
		
		out.append(']')
		
		#if the output is empty
		if len(out) == 2:
			return ''
		else:
			return newline.join(out)

class diffObject( smwObject ):
	'''Reverse of smwObject - takes the diff output and makes it good for writing to an SMW file'''
	def convertChildRefs(self):
		self.isParent = True
		self.setKey( smw.key.childCount, len(self.children) )  #count of children
			
	def fixSignals(self, signalBackTable):
		'''Turn all inputs and outputs from signal names to H references'''
		if self.type == smw.type.symbol:
			#inputCount = int(self.data['mI'])
			for key in self._data:
				try:
					#find valid I5 or O10 kind of keys
					c = int(key[1:])
				except:
					c = False
				
				if c:
					#if this is an input or output (I# or O#)
					if key[:1] in ['I', 'O']:
						#replace the name with the ref value from the back signal table
						sigName = self.getKey(key)
						#print self.name, key, sigName
						#sigObj = self.references['back-'+smw.type.signal][ sigName ]
						sigObj = signalBackTable[ sigName ]
						self.setKey(key, sigObj.H )
						#if this signal is used, make sure it isn't hidden
						sigObj.hidden = False

class inFile:
	'''Splits a data stream containing SMW objects and makes them ready for diff'ing'''
	obj = smwObject
	reservedSignals = {
		'1': obj( newline.join([smw.key.type+'='+smw.type.signal, 'H=1', 'Nm=0']) ),
		'2': obj( newline.join([smw.key.type+'='+smw.type.signal, 'H=2', 'Nm=1']) ),
		'3': obj( newline.join([smw.key.type+'='+smw.type.signal, 'H=3', 'Nm=Local']) )
		}
	firstSignal = 4
	
	def __init__(self, data):
		self.objOrder = []
		self.references = {}
		self.objList = {}
		
		self.references[ smw.type.signal ] = dict(self.reservedSignals)
		
		self.readData(data)

	def readData(self, data):
		if type(data) == type(''):
			chunks = data.split(newline+']'+newline)
		else:
			chunks = data
			
		for chunk in chunks:
			if not chunk:
				continue
			newObj = self.obj(chunk)
			#self.data.append(newObj)
			
			if not newObj.type in self.objOrder:
				self.objOrder.append(newObj.type)
				self.objList[newObj.type] = []
				
			self.addReferences( newObj )
				
			self.objList[newObj.type].append(newObj)
						
		self.objectsImported()
	
	def objectsImported(self):
		global masterObjOrder
		masterObjOrder.integrate(self.objOrder)
		
		
		# self.references[ symbol ]  is a dict
		signalTable = self.references[ smw.type.signal ]
		for key in self.references[ smw.type.symbol ]:
			self.references[ smw.type.symbol ][key].fixSignals(signalTable)
	
	def addReferences( self, newObj ):
		#if we have a ref (H), store ref in the lists (as dict)
		if newObj.H:
			#if there is no array for this object type, create one
			if not self.references.has_key(newObj.type):
				self.references[newObj.type] = {}
			#store our reference filed by ref (H)
			self.references[newObj.type][newObj.H] = newObj
						
	
	def __len__(self):
		count = 0
		for objType in self.objList:
			count += len(self.objList[objType])
		return count
		
	#return all children (and children's children) in order
#  	def childList(self, list, refs):
#  		result = []
#  		for ref in refs:
#  			result.append( str(list[ref]) )
#  			if list[ref].children:
#  				result.extend( self.childList(list,list[ref].children) )
#  		result.append( str(self.folderEnd) )
#  		return result
	
#	def symbolList(self):
#		#step through all symbols, add top levels directly, add any children immediately following
# 		out = []
# 		for obj in self.objList[smw.type.symbol]:
# 			#if the object has no parents
# 			if not obj.parent:
# 				out.append( str(obj) )
# 				if obj.children:
# 					out.extend( self.childList(self.references[smw.type.symbol], obj.children) )
# 		return out
		
	
	def diffOut(self, objType):
		out = []
		#if objType == smw.type.symbol:
		#	return self.symbolList()
		#elif
		if not objType in self.objList:
			return out
		else:
			#step through all objects and add
			for obj in self.objList[objType]:
				out.append( str(obj) )
		
		return out


class outFile( inFile ):
	'''Takes a list of SMW Objects and turns them back into a legal SMW file'''
	def __init__(self, data):
		self.objOrder = []
		self.references = {}
		self.objList = {}
		
		self.buildRefTables( smw.type.signal, dict(self.reservedSignals) )
		
		self.readData(data)

	#override the object type with the diffObject
	obj = diffObject
	refCount = {}
	
	def buildRefTables( self, type, base={} ):
		self.references[type] = {}
		self.references[type][''] = base
		#build the A and B redirected dict.  Any failed lookups in A or B will try the base
		for file in ['A', 'B']:
			self.references[type][file] = redict()
			self.references[type][file].setBase(base)
		
	
	#override the addReferences routine
	def addReferences( self, newObj ):
		#if the object has an H value, fix it and save a reference
		if newObj.H or newObj.HA or newObj.HB:
			#if there is no array for this object type, create one
			if not self.references.has_key(newObj.type):
				self.buildRefTables( newObj.type )
			
			#assume all signals are hidden until referenced otherwise
			if newObj.type == smw.type.signal:
				newObj.hidden = True

# done in build forward references			
# 			for file in ['', 'A', 'B']:
# 				if newObj.refs[file]:
# 					print newObj.type, file, newObj.refs[file]
# 					self.references[newObj.type][file][ newObj.refs[file] ] = newObj
			
			#self.references[newObj.type][newObj.H] = newObj
	
# 	def correctSymbolArrangement( self ):
# 		'''Move the top-level symbols to the front of the list'''
# 		#note that this only can be done after the folder hierarchy has been worked out
# 		topSymbols = []
# 		otherSymbols = []
# 		
# 		for obj in self.objList[ smw.type.symbol ]:
# 			if not obj.parent:
# 				topSymbols.append(obj)
# 			else:
# 				otherSymbols.append(obj)
# 				
# 		self.objList[ smw.type.symbol ] = topSymbols + otherSymbols
	
	def correctObjectCrossRef( self, obj, list, key ):
		'''Corrects a given cross ref.
		   obj is the object to modify
		   list is the list where we look up the value
		   key is the obj key we use to perform the lookup'''
		#look in this file:
		try:
			file = obj.getKeySource( key )
		except KeyError:
			raise SMWError('Key not in object.  Key='+key)
		#for this key (ie, 'A' file key 51)
		try:
			fileRef = obj.getKey( key )
		except KeyError:
			raise SMWError('Key not in object.  Key='+key)
		#here's the object that it points to
		global r, o
		o = obj
		r = self.references
		try:
			refObj = self.references[ list ][ file ][ fileRef ]
		except KeyError:
			#raise KeyError('Could not find key in references.  list='+list+' file='+file+' fileRef='+str(fileRef) )
			logging.warn('Could not find key in references.  obj='+obj.type+' '+obj.H+' -> '+list+' ('+file+') '+str(fileRef) )
			return
			
		#set our ref to that object's H value
		obj.setKey( key, refObj.H )
	
	def correctAllCrossRefs( self ):
		'''Steps through all objects and corrects the cross references.
		   depends on an accurate references table.'''
		for list in self.objList:
			for obj in self.objList[list]:
				#if any of the crossref stuff is in this object, correct it
				for xref in smw.crossref:
					try:
						#lookup the xref in the crossreferenced list
						self.correctObjectCrossRef( obj, smw.crossref[xref], xref )
					except SMWError:
						pass
				
				#correct any parent references
				try:
					self.correctObjectCrossRef( obj, list, smw.key.parent )
				except SMWError:
					pass

				#if there are any child references, correct them
				if not obj.isParent:
					continue				
				
				child = 1
				while True:
					try:
						#look up children in the current list
						self.correctObjectCrossRef( obj, list, 'C'+str(child) )
						child += 1
					except SMWError:
						break
				#obj.setKey( smw.key.childCount, child ) - probably not needed
	
	def getUniqueRef( self, ref, obj ):
		'''Determine and set a unique H ref for a given object '''
		try:
			refList = self.references[ref]['final']
		except:
			refList = { '':False } #disallow using null
			self.references[ref]['final'] = refList
		
		try:
			if refList[obj.H] == obj:
				return obj.H
		except:
			pass
		
		H = ''
		# try and register this object with the original ref, then the B ref, then A
		for Href in [ '', 'B', 'A' ]:
			H = obj.refs[Href]
			if not refList.has_key( H ):
				refList[ H ] = obj
				return H
		
		H = obj.H or obj.HB or obj.HA
		# if we have failed to find a spot (likely due to a conflict), increment until we find one
		# (could instead look at the highest match, but that may not fill in holes properly)
		while refList.has_key( H ):
			# H may be str or float
			try:
				H = str( int( H ) +1 )
			except:
				H = str( float( H ) +1 )
		
		refList[ H ] = obj
		return H
		
		
	
	def buildForwardReference( self, ref ):
		'''Build a forward reference table, creating or updating the H values as needed'''
# 		H = 1
# 		if ref == smw.type.signal:
# 			H = self.firstSignal
			
		for obj in self.objList[ref]:
			#get a unique ref for this obj
			newH = self.getUniqueRef( ref, obj )
			
			#register this object with its different lists based on its original refs (for lookup)
			for file in ['', 'A', 'B']:
				if obj.refs[file]:
					logging.debug( ref +' '+ file +' '+ obj.refs[file] + ' -> ' + newH )
					self.references[ref][file][ obj.refs[file] ] = obj
			#set the new unique ref (for output)
			obj.setRef( newH )
			
			
			
		
	def buildBackReference( self, forward, back={} ):
		'''Build a back reference table for needed entries'''
		#assumes each item has a unique name and references table is a list
		
		#back = {}
		#forward = self.references[ref]
		
		for objref in forward:
			obj = forward[objref]
			back[ obj.name ] = obj
			
		return back
	
# 	def recreateParentage( self ):
# 		'''walk through the symbol list and rebuild the folder information'''
# 		children = []
# 		for list in self.objList:
# 			pass
# 		#TODO: FINISH THIS!!
		
# 		symbolList = self.objList[ smw.type.symbol ]
# 		parentStack = []
# 		childrenStack = []
# 		parent = False
# 		children = []
# 		
# 		for obj in symbolList:
# 			children.append( obj )
# 			if parent:
# 				obj.parent = parent
# 				#obj.setKey( smw.key.parent, str(parent.H) )
# 		
# 			if obj.hasKey( smw.mark.folder ):
# 				if obj.getKey( smw.mark.folder ) == 'start':
# 					obj.delKey( smw.mark.folder )
# 					parentStack.append(parent)
# 					childrenStack.append(children)
# 					parent = obj
# 					children = []
# 				else:  #assume 'end'
# 					# don't include this end marker in the final file
# 					obj.hidden = True
# 					children.pop()
# 					parent.children = children
# 					
# 					parent = parentStack.pop()
# 					children = childrenStack.pop()
# 					#parent.setKey(  smw.key.childCount, str( len(children) )  )
# 					
# 					#childNum = 0
# 					#for child in children:
# 					#	childNum += 1
# 					#	parent.setKey( 'C'+str(childNum), str(child) )
# 					#	
# 					#parent = parentStack.pop()
# 					#children = childrenStack.pop()
	
# 	def rebuildFolderReferences(self):
# 		'''walk through the symbol list and recreate the parent/child reference IDs'''
# 		for obj in self.objList[ smw.type.symbol ]:
# 			#if obj.parent:
# 			#	obj.newKey( smw.key.parent, obj.parent.H )
# 			
# 			if obj.children:
# 				obj.newKey( smw.key.childCount, len(obj.children) )
# 				childNum = 0
# 				for child in obj.children:
# 					childNum += 1
# 					obj.newKey( 'C'+str(childNum), child.H )
					
	#override the objectsImported (end of __init__)
	def objectsImported(self):
		'''Perform the actions needed to turn these objects back into a happy SMW file'''
#		if self.objList.has_key( smw.type.symbol ):
#			self.recreateParentage()
#			self.correctSymbolArrangement()
		
		for smwType in self.references:
			self.buildForwardReference( smwType )
		
		global signalBackTable
		signalBackTable = self.buildBackReference( self.references[smw.type.signal][''] )
		signalBackTable = self.buildBackReference( self.references[smw.type.signal]['A'], signalBackTable )
		signalBackTable = self.buildBackReference( self.references[smw.type.signal]['B'], signalBackTable )
		# Re-encode the signal references in the symbol objects
		#signalBackTable = self.references[ 'back-' + smw.type.signal ]
		
		if self.objList.has_key( smw.type.symbol ):
			for obj in self.objList[ smw.type.symbol ]:
				obj.fixSignals(signalBackTable)
				
#			self.rebuildFolderReferences()
		
		self.correctAllCrossRefs()

	
	
	def __str__(self):
		out = []
		#step through all objects and add
		for objType in self.objOrder:
			for obj in self.objList[objType]:
				if not obj.hidden:
					serialized = str(obj)
					if(serialized):
						out.append( serialized )
		
		
		return newline.join(out)

########################################################
##
##   File operations
##
########################################################
def read_file(filename):
    try:
        f = open(filename, 'rb')
        l = f.readlines()
        f.close()
    except IOError, err:
        print "can't open file '" + filename + "'. aborting."
        sys.exit(-1)
    else:
        return l

		
def merge():
	global ai, bi, xi
	global result, oresult, conflict
	
	result = []
	oresult = {}
	conflict = False
	objResult = []
        mergeHandler = smw.merge['unknown']
	
	for objType in masterObjOrder:
		try:
                        mergeHandler = smw.merge[objType]
                except:
                        mergeHandler = smw.merge['unknown']
                        logging.info( 'Unhandled merge object: '+objType+'.  Using Conservative SMW merge.')

		if mergeHandler:
                        objResult = mergeHandler( ai.diffOut(objType), bi.diffOut(objType), xi.diffOut(objType) )
                	oresult[objType] = objResult
                        logging.info( objType + ' - conflict: ' + str(conflict) ) 
                	if objResult.conflict:
                        	conflict = True
		
                        result.extend(objResult)
		
	logging.info('conflict = ' + str(conflict))
	
	global o
	o = outFile(result)
	
	if options.output_file:
		f = open(sys.argv[4], 'wb')
		f.write(str(o))
		f.write(newline)
		f.close()
	else:
		print str(o)

def main():	
	parser = OptionParser(usage="usage: %prog [options] your-file their-file original-file",
							version="%prog " + version, 
							description=program_description,
							epilog=copyright)
	parser.add_option("-o", "--output-file", dest="output_file",
						help="write result to FILE instead of stdout", metavar="FILE")
	parser.add_option('-l', '--logging-level', dest="log_level", metavar="LEVEL", choices=LOGGING_LEVELS.keys(),
						help='Logging level.  '  'LEVEL can be "' + '", "'.join(LOGGING_LEVELS.keys()) + '"')
	parser.add_option("-f", "--log-file", dest="log_file",
						help="write debugging information to FILE", metavar="FILE")
	
	global options
	(options, args) = parser.parse_args()
	
	logging_level = LOGGING_LEVELS.get(options.log_level, logging.NOTSET)
	logging.basicConfig(level=logging_level, filename=options.log_file,
						  format='%(asctime)s %(levelname)s: %(message)s',
						  datefmt='%Y-%m-%d %H:%M:%S')
	
	if len(args) > 2:
		global af, bf, xf
		af = "".join(read_file(sys.argv[1]))
		bf = "".join(read_file(sys.argv[2]))
		xf = "".join(read_file(sys.argv[3]))
		global ai, bi, xi
		ai = inFile(af)
		bi = inFile(bf)
		xi = inFile(xf)
		
		merge()
	else:
		parser.print_help()


if __name__ == '__main__':
	main()
