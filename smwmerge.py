#!/usr/bin/env python3

import difflib
import sys
import re
import logging

from optparse import OptionParser

newline = '\r\n'

# SMW files are single-byte text (Windows-1252).  Latin-1 maps every byte to
# one character, so reading and writing with it round-trips the file exactly.
file_encoding = 'latin-1'

program_description = """
Perform a three-way merge on a SIMPL Windows file.
Given a base file (original-file), changes that you've made to that file (your-file)
and changes someone else has made to that file (their-file), both your changes
and their changes will be merged into a final output.
"""

copyright = """
© Copyright 2026 Stephen Genusa

Copyright Ian Epperson.  Parts based on a file called mymerge.py written by Marcos Chaves.

This software may be used and distributed according to the terms
of the GNU General Public License, incorporated herein by reference.
"""

version = "0.5"

# The side that wins when both sides change the same thing in different ways.
# 'A' is your-file, 'B' is their-file.
primary = 'B'
sideNames = {'A': 'your', 'B': 'their'}

def secondary():
	return 'A' if primary == 'B' else 'B'

# Where a symbol cannot take both sides' changes, the side that loses is kept
# as a commented-out copy in a folder of this name.
conflictFolder = True
conflictFolderName = 'Merge Conflicts'

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
		if a!=False and b!=False and x!=False:
			self.conflict, self.result = self.threeWay(a,b,x)
			self.ran = True
			
		elif a!=False and b!=False:
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

	def _matches(self, x, other):
		'''Map the place of each element of x to its place in the other list, for the elements both have'''
		found = {}
		matcher = difflib.SequenceMatcher( None, x, other, autojunk=False )
		for block in matcher.get_matching_blocks():
			for offset in range(block.size):
				found[block.a + offset] = block.b + offset
		return found
	
	#perform a three-way merge using _conflictManger for any conflicts
	def threeWay(self, a, b, x, a_name = 'A', b_name = 'B'):
		'''The elements of x that both sides still have stay where they are.  An
		   element of x that either side dropped is dropped.  Between the elements
		   that stay, whatever each side added is put in.'''
		in_a = self._matches(x, a)
		in_b = self._matches(x, b)
		from_x_a = set( in_a.values() )
		from_x_b = set( in_b.values() )
		
		self.a = a
		self.b = b
		self.x = x
		
		m = []
		had_conflict = False
		index_a = 0
		index_b = 0
		kept = [ index for index in range(len(x)) if index in in_a and index in in_b ]
		
		# one more turn after the last kept element, for what was added at the end
		for index in kept + [None]:
			if index is None:
				end_a, end_b = len(a), len(b)
			else:
				end_a, end_b = in_a[index], in_b[index]
			
			added_a = [ a[i] for i in range(index_a, end_a) if not i in from_x_a ]
			added_b = [ b[i] for i in range(index_b, end_b) if not i in from_x_b ]
			resolved, added = self._mergeAdded( added_a, added_b, a_name, b_name )
			m.extend( added )
			if not resolved:
				had_conflict = True
			
			if index is not None:
				m.append( x[index] )
			index_a = end_a + 1
			index_b = end_b + 1

		return had_conflict, m
	
	def _mergeAdded(self, added_a, added_b, a_name, b_name):
		'''Combine what each side added in the same place.
		   Returns an indication if any conflict was resolved (bool) and the elements for the result.'''
		if primary == 'A':
			first, second = added_a, added_b
		else:
			first, second = added_b, added_a
		
		# the same element added by both sides
		m = []
		same = [ element for element in first if element in second ]
		for element in same:
			m.extend( self._identicalAdd( element ) )
		
		only_a = [ element for element in added_a if not element in same ]
		only_b = [ element for element in added_b if not element in same ]
		
		if only_a and only_b:
			# possible conflict.  Attempt last ditch merge
			if len(only_a) == 1 and len(only_b) == 1:
				mergedLine = self._lastDitchMerge( only_a[0], only_b[0] )
				if mergedLine:
					return True, m + [mergedLine]
		
		ca = [ self._preprocessAdd( element, a_name ) for element in only_a ]
		cb = [ self._preprocessAdd( element, b_name ) for element in only_b ]
		if ca and cb:
			# conflict - pass the lists to the handler
			resolved, cm = self._conflictManager( ca, cb, ('', '') )
			return resolved, m + cm
		
		return True, m + ca + cb
	
	#both sides added the same element - return what goes into the result
	def _identicalAdd(self, element):
		return [ self._preprocessAdd( element, primary ) ]
	
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
		'''Only return the primary file's changes during conflict'''
		if primary == 'A':
			return True, a
		return True, b

class MergeGreedy( Merge ):
	def _conflictManager(self, a, b, lastStatus):
		'''Return the sum of all a and b, the primary file's first.'''
		if primary == 'A':
			return True, a + b
		return True, b + a


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
		
	#Handles are numbered separately in each file, so a new object that reads the
	#same on both sides is still two objects: each side made its own.
	#(Signals are known by name, and a copy that ends up unused is not written.)
	def _identicalAdd(self, element):
		handle = dict( self._objectLines(element) ).get( smw.key.ref )
		if handle is not None and not handle in self.baseHandles:
			return [ self._preprocessAdd( element, primary ), self._preprocessAdd( element, secondary() ) ]
		return [ self._preprocessAdd( element, primary ) ]
	
	def threeWay(self, a, b, x, a_name = 'A', b_name = 'B'):
		self.keyConflict = False
		self.baseHandles = self._identities(x)
		a, b = self._settleDeletedObjects( list(a), list(b), x )
		a, b = self._mergeChangedObjects( a, b, x )
		had_conflict, m = Merge.threeWay( self, a, b, x, a_name, b_name )
		return had_conflict or self.keyConflict, m
	
	def _objectLines(self, element):
		'''The key=value lines of an object, as [key, value] pairs'''
		return [ line.split('=',1) for line in element.split(newline) if '=' in line ]
	
	def _identities(self, elements):
		'''Map each object's handle to its place in the list.
		   A type with a single object and no handles (the header) is known by its type.'''
		found = {}
		for index, element in enumerate(elements):
			keys = dict( self._objectLines(element) )
			identity = keys.get( smw.key.ref )
			if identity is None and len(elements) == 1:
				identity = keys.get( smw.key.type )
			if identity is not None:
				found[identity] = index
		return found
	
	#an object one side deleted and the other side changed (stub)
	def _settleDeletedObjects(self, a, b, x):
		return a, b
	
	#told of each object that had keys both sides changed differently (stub)
	def _objectConflict(self, original, mine, theirs):
		pass
	
	def _label(self, element):
		'''The type, handle and name of an object, for a message'''
		keys = dict( self._objectLines(element) )
		return ( keys.get(smw.key.type, ''), keys.get(smw.key.ref, ''), keys.get(smw.key.name, keys.get(smw.key.comment1, '')) )
	
	def _mergeChangedObjects(self, a, b, x):
		'''Where both sides changed the same object in different ways, merge it
		   key by key and give both sides the result.'''
		in_a = self._identities(a)
		in_b = self._identities(b)
		for identity, index in self._identities(x).items():
			if not ( identity in in_a and identity in in_b ):
				continue
			original, mine, theirs = x[index], a[ in_a[identity] ], b[ in_b[identity] ]
			if mine == original or theirs == original or mine == theirs:
				continue
			merged = self._mergeObject( original, mine, theirs )
			a[ in_a[identity] ] = merged
			b[ in_b[identity] ] = merged
		return a, b
	
	def _mergeObject(self, original, mine, theirs):
		'''Three-way merge of the keys of one object.  A key changed on one side
		   takes that side's value; changed on both, it takes the primary's.'''
		x = dict( self._objectLines(original) )
		a = dict( self._objectLines(mine) )
		b = dict( self._objectLines(theirs) )
		sides = {'A': a, 'B': b}
		
		# keep the keys in the order of the two sides
		keys_a = [ pair[0] for pair in self._objectLines(mine) ]
		keys_b = [ pair[0] for pair in self._objectLines(theirs) ]
		order = []
		for item in self.differ.compare( keys_a, keys_b ):
			if not item.startswith( self.marker.inline ) and not item[2:] in order:
				order.append( item[2:] )
		
		out = ['[']
		conflicts = 0
		for key in order:
			if key == smw.key.child:
				out.extend( self._mergeChildren( mine, theirs ) )
				continue
			
			if a.get(key) == b.get(key):
				source = primary
			elif b.get(key) == x.get(key):
				source = 'A'
			elif a.get(key) == x.get(key):
				source = 'B'
			else:
				source = primary
				self.keyConflict = True
				conflicts += 1
				logging.warning( 'Conflict in %s %s (%s): %s is %r in your file and %r in their file.  Kept %ss.'
					% ( x.get(smw.key.type, ''), x.get(smw.key.ref, ''), x.get(smw.key.name, x.get(smw.key.comment1, '')),
						key, a.get(key, ''), b.get(key, ''), sideNames[source] ) )
			
			value = sides[source].get(key)
			if value is None:
				continue
			line = key + '=' + value
			if source != primary:
				# the rest of the object is marked as the primary's when it is added
				line = SMWMerger._preprocessAdd( self, line, source )
			out.append( line )
		
		if conflicts:
			self._objectConflict( original, mine, theirs )
		
		out.append(']')
		return newline.join(out)
	
	def _mergeChildren(self, mine, theirs):
		'''All the children either side lists.  Children that no longer exist are dropped when the file is written.'''
		children = {}
		for side, element in ( ('A', mine), ('B', theirs) ):
			children[side] = [ pair[1] for pair in self._objectLines(element) if pair[0] == smw.key.child ]
		first, second = children[primary], children[secondary()]
		out = [ smw.key.child + '=' + child for child in first ]
		out.extend( smw.key.child + '-' + secondary() + '=' + child for child in second if not child in first )
		return out


class SMWMergeGreedy( SMWMerger, MergeGreedy ):
	pass

class MergeMaxKeys( Merge ):
	def _lastDitchMerge(self, element_a, element_b):
		# perform a line-by-line merge and keep the highest value keys
		# will always return a completed result
		result = self.twoWay( element_a.split(newline), element_b.split(newline) )
		final = []
		position = {}	#where each key sits in final
		
		for line in result:
			key, separator, value = line.partition('=')
			if not separator:
				final.append( line )
			elif key not in position:
				position[key] = len(final)
				final.append( line )
			else:
				kept = final[ position[key] ].partition('=')[2]
				if self._valueOrder(value) > self._valueOrder(kept):
					final[ position[key] ] = line
		
		return newline.join(final)
	
	numberFinder = re.compile( '([0-9]+)' )
	def _valueOrder(self, value):
		'''Sort key that compares the numbers inside a value as numbers, so 1000 > 650 and 4.10 > 4.9'''
		parts = self.numberFinder.split(value)
		#split() alternates text and digits, starting with text
		return [ int(part) if index % 2 else part for index, part in enumerate(parts) ]
		
	def _conflictManager(self, a, b, lastStatus):
		#should never ever reach this
		raise NotImplementedError('MergeMaxKeys somehow fell to the Conflict Manager.')
		
class MergeSymbols( SMWMergeGreedy ):
	'''Different symbols added in the same place are all kept.
	   The side that loses a conflict in a symbol is set aside whole, as
	   (side, symbol) in conflictCopies, to go in the conflict folder.'''
	
	def threeWay(self, a, b, x, a_name = 'A', b_name = 'B'):
		self.conflictCopies = []
		return SMWMergeGreedy.threeWay( self, a, b, x, a_name, b_name )
	
	def _canCopy(self, element):
		'''A symbol that stands by itself.  A subsystem has children, and a device
		   or Smart Graphics symbol belongs to another object that cannot be copied.'''
		keys = dict( self._objectLines(element) )
		if keys.get( smw.key.symType ) in smw.symType.folders or not smw.key.parent in keys:
			return False
		return not any( key in keys for key in smw.key.ownedBy + (smw.key.childCount,) )
	
	def _setAside(self, side, element):
		if not ( conflictFolder and self._canCopy(element) ):
			return
		self.conflictCopies.append( (side, element) )
		logging.warning( '%s version of %s %s (%s) is in the %s folder, commented out.'
			% ( ( sideNames[side].capitalize(), ) + self._label(element) + ( conflictFolderName, ) ) )
	
	def _objectConflict(self, original, mine, theirs):
		self._setAside( secondary(), {'A': mine, 'B': theirs}[ secondary() ] )
	
	def _settleDeletedObjects(self, a, b, x):
		'''A symbol one side deleted and the other side changed.  The primary has
		   its way: its change stays, or its deletion sets the changed symbol aside.'''
		sides = {'A': a, 'B': b}
		found = {'A': self._identities(a), 'B': self._identities(b)}
		dropped = {'A': [], 'B': []}
		for identity, index in self._identities(x).items():
			if ( identity in found['A'] ) == ( identity in found['B'] ):
				continue
			changer = 'A' if identity in found['A'] else 'B'
			deleter = 'B' if changer == 'A' else 'A'
			element = sides[changer][ found[changer][identity] ]
			if element == x[index] or not self._canCopy(element):
				continue
			
			self.keyConflict = True
			did = {changer: 'changed', deleter: 'deleted'}
			logging.warning( 'Conflict in %s %s (%s): %s in your file and %s in their file.  Kept %ss.'
				% ( self._label(x[index]) + ( did['A'], did['B'], sideNames[primary] ) ) )
			if deleter == primary:
				dropped[changer].append( found[changer][identity] )
				self._setAside( changer, element )
		
		for side in sides:
			sides[side] = [ element for index, element in enumerate(sides[side]) if not index in dropped[side] ]
		return sides['A'], sides['B']
		

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

#each signal in the original file, by name
baseSignals = {}



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
		Et       = 'Et' #Ethernet settings
		Cs       = 'Cs' #Connection sheet
		
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
		DvCrossRef = 'DvH'
		EtCrossRef = 'EtH'
		CsCrossRef = 'CsH'
		address  = 'Ad'
		flag     = 'DvF'
		commentedOut = 'OpF'	#0=commented out
		byHand       = 'HandF'	#commented out itself, under a parent that is not
		propagated   = 'PropF'	#commented out because its parent is
		#keys that tie a symbol to an object of another type
		ownedBy  = ( 'DvH', 'CedH', 'ChdH' )
		#the comment flags are written after the last of these
		beforeFlags = ( 'PrH', 'CF', 'n1I', 'n2I', 'n1O' )
		#what a new subsystem takes from one already in the program
		folderKeys = ( 'SmC', 'Nm', 'ObjVer', 'SmVr' )
	
	crossref = {
		#'PrH': current table
		key.SmCrossRef: type.symbol,
		key.CmCrossRef: type.Cm,
		key.DbCrossRef: type.Db,
		key.DvCrossRef: type.device,
		key.EtCrossRef: type.Et,
		key.CsCrossRef: type.Cs,
		}
		
	
	class symType:
		folder  = '156'
		folders = ( '156', '157' )	#subsystems and the fixed top-level folders
		folderName = 'SUBSYSTEM'
	
	slotFlag = 'Sl'		#value of the flag key on a slot
		
	#Objects changed on both sides are merged key by key before these run, so
	#what is left for them is different objects added in the same place.
	merge = {
		''            : MergeConservative,
		type.symbol   : MergeSymbols,
		type.signal   : SMWMergeGreedy,
		type.progInfo : MergeMaxKeys,
		type.openSm   : False,				#do not try and merge any open symbols - not worth the effort
		'unknown'     : SMWMergeGreedy,
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
		
		# convert child keys to remove specific order number
		if self.hasKey( smw.key.childCount ):
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
			
		if refKey in self._data and str(self._data[refKey]) != value:
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
		return key in self._data
	
	def delKey(self, key):
		try:
			del self._data[key]
		except:
			pass
	
	def insertKey(self, key, value, position):
		'''add a new key at the given place in the order of the keys'''
		self._data[key] = self._key(key, value)
		self._dataOrder.insert( position, key )
	
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
	
	def setChildren(self, handles):
		'''Replace the list of children with the given handles, in the given order'''
		oldKeys = [ child.key for child in self.children ]
		if oldKeys:
			position = self._dataOrder.index( oldKeys[0] )
		elif self.hasKey( smw.key.childCount ):
			position = self._dataOrder.index( smw.key.childCount ) + 1
		else:
			#not a parent object
			return
		
		for key in oldKeys:
			del self._data[key]
			self._dataOrder.remove(key)
		
		self.children = []
		for handle in handles:
			child = self._key( 'C' + str( len(self.children) + 1 ), handle )
			self._data[child.key] = child
			self._dataOrder.insert( position + len(self.children), child.key )
			self.children.append( child )
		
		self.setKey( smw.key.childCount, len(self.children) )
			
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

def expandHandles(text):
	'''Turn a handle list like 7.9,12 into ['7', '8', '9', '12']'''
	handles = []
	for part in text.split(','):
		first, dot, last = part.partition('.')
		handles.extend( str(h) for h in range( int(first), int(last or first) + 1 ) )
	return handles

def countHandles(text):
	'''How many handles a handle list like 7.9,12 holds, without building it.
	   Raises ValueError when the list makes no sense.'''
	count = 0
	for part in text.split(','):
		first, dot, last = part.partition('.')
		size = int(last or first) - int(first) + 1
		if size < 1:
			raise ValueError( 'Handle range runs backwards: ' + part )
		count += size
	return count

def compressHandles(handles):
	'''Turn ['7', '8', '9', '12'] into the handle list 7.9,12'''
	runs = []
	for handle in handles:
		handle = int(handle)
		if runs and runs[-1][1] == handle - 1:
			runs[-1][1] = handle
		else:
			runs.append( [handle, handle] )
	return ','.join( str(a) if a == b else str(a) + '.' + str(b) for a, b in runs )

def expandDeviceRanges(chunk):
	'''A run of identical empty slots is stored as one object with a list of
	   handles and one address for each.  Return one object per slot.'''
	lines = chunk.split(newline)
	if not smw.key.type + '=' + smw.type.device in lines:
		return [chunk]
	
	position = {}
	for index, line in enumerate(lines):
		key = line.split('=',1)[0]
		if key in ( smw.key.ref, smw.key.address ):
			position[key] = index
	if len(position) < 2:
		return [chunk]
	
	handleLine, addressLine = position[smw.key.ref], position[smw.key.address]
	handles = lines[handleLine].split('=',1)[1]
	addresses = lines[addressLine].split('=',1)[1].split(',')
	if handles.isdigit():
		return [chunk]
	#check the size before building the list - a bad range could claim millions of slots
	try:
		if countHandles(handles) != len(addresses):
			return [chunk]
	except ValueError:
		return [chunk]
	handles = expandHandles(handles)
	
	chunks = []
	for handle, address in zip(handles, addresses):
		lines[handleLine] = smw.key.ref + '=' + handle
		lines[addressLine] = smw.key.address + '=' + address
		chunks.append( newline.join(lines) )
	return chunks


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
		if isinstance(data, str):
			chunks = data.split(newline+']'+newline)
		else:
			chunks = data
		
		chunks = [ single for chunk in chunks for single in expandDeviceRanges(chunk) ]
			
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
			if not newObj.type in self.references:
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
	def __init__(self, data, conflictCopies=()):
		self.objOrder = []
		self.references = {}
		self.objList = {}
		#(side, symbol) for each symbol to go in the conflict folder
		self.conflictCopies = list(conflictCopies)
		
		self.buildRefTables( smw.type.signal, dict(self.reservedSignals) )
		
		self.readData(data)

	#override the object type with the diffObject
	obj = diffObject
	refCount = {}
	
	#The control system device (Dv H=2) has PrH=1, a root that has no object of its own
	implicitRoot = { smw.type.device: '1' }
	
	def buildRefTables( self, type, base=None ):
		#each type needs its own table - handles are only unique within a type
		if base is None:
			base = {}
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
			if not newObj.type in self.references:
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
	
	def correctObjectCrossRef( self, obj, list, key, warn=True ):
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
		refObj = self.findReference( list, file, fileRef )
		if refObj is None:
			if not warn or fileRef == self.implicitRoot.get(list):
				return
			logging.warning('Could not find key in references.  obj='+obj.type+' '+obj.H+' -> '+list+' ('+file+') '+str(fileRef) )
			return
			
		#set our ref to that object's H value
		obj.setKey( key, refObj.H )
	
	def findReference( self, list, file, ref ):
		'''The object that a handle in one of the files stands for, or None.
		   An object changed on one side is filed under that side only, so when
		   the reference's own file does not have it, look in the others.'''
		for table in [file] + [ f for f in ('', primary, secondary()) if f != file ]:
			try:
				return self.references[ list ][ table ][ ref ]
			except KeyError:
				continue
		return None
	
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
						#a child that has gone is dropped by rebuildChildLists, so no warning for those
						self.correctObjectCrossRef( obj, list, 'C'+str(child), warn=not obj.children )
						child += 1
					except SMWError:
						break
				#obj.setKey( smw.key.childCount, child ) - probably not needed
	
	def rebuildChildLists( self, list ):
		'''Make each parent list exactly the objects that name it as their parent.
		   Both sides may have added children to one parent, or one side may have
		   removed a child that the other side still lists.  The existing order is
		   kept and children missing from the list are added at the end.
		   Depends on corrected cross references.'''
		if not list in self.objList:
			return
		
		childrenOf = {}
		for obj in self.objList[list]:
			parent = obj.getKey( smw.key.parent )
			if parent:
				childrenOf.setdefault( parent, [] ).append( obj.H )
		
		for obj in self.objList[list]:
			actual = childrenOf.get( obj.H, [] )
			ordered = []
			for child in obj.children:
				if child.value in actual and not child.value in ordered:
					ordered.append( child.value )
			for child in actual:
				if not child in ordered:
					ordered.append( child )
			
			if ordered != [ child.value for child in obj.children ]:
				obj.setChildren( ordered )
	
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
		# try and register this object with the original ref, then the primary's, then the other
		for Href in [ '', primary, secondary() ]:
			H = obj.refs[Href]
			if not H in refList:
				refList[ H ] = obj
				return H
		
		H = obj.H or obj.refs[primary] or obj.refs[secondary()]
		# if we have failed to find a spot (likely due to a conflict), increment until we find one
		# (could instead look at the highest match, but that may not fill in holes properly)
		while H in refList:
			# H may be str or float
			try:
				H = str( int( H ) +1 )
			except:
				H = str( float( H ) +1 )
		
		refList[ H ] = obj
		return H
		
		
	
	def takeNewRef( self, obj ):
		'''Give an object the handle after the highest one in use'''
		final = self.references[obj.type]['final']
		handle = str( max( [0] + [ int(H) for H in final if H.isdigit() ] ) + 1 )
		final[handle] = obj
		obj.setRef( handle )
	
	def newFolder( self, like, parent, reason, caption ):
		'''A commented-out subsystem, laid out like one already in the program'''
		lines = [ '[', smw.key.type + '=' + smw.type.symbol, smw.key.ref + '=' ]
		if like:
			lines.extend( key + '=' + like.getKey(key) for key in like._dataOrder if key in smw.key.folderKeys )
		else:
			lines.extend([ smw.key.symType + '=' + smw.symType.folder, smw.key.name + '=' + smw.symType.folderName, 'ObjVer=1' ])
		lines.append( smw.key.parent + '=' + parent.H )
		if not like or like.hasKey( smw.key.symComplete ):
			lines.append( smw.key.symComplete + '=2' )
		lines.extend([ smw.key.commentedOut + '=0', reason + '=1' ])
		lines.extend( caption )
		lines.extend([ smw.key.childCount + '=0', ']' ])
		
		folder = self.obj( newline.join(lines) )
		self.takeNewRef( folder )
		return folder
	
	def commentOut( self, obj ):
		'''Mark a symbol as commented out because the folder it is in is'''
		position = 1 + max( obj._dataOrder.index(key) for key in smw.key.beforeFlags if key in obj._dataOrder )
		if obj.hasKey( smw.key.commentedOut ):
			position = obj._dataOrder.index( smw.key.commentedOut ) + 1
		else:
			obj.insertKey( smw.key.commentedOut, '0', position )
			position += 1
		if not obj.hasKey( smw.key.propagated ):
			obj.insertKey( smw.key.propagated, '1', position )
	
	def addConflictFolder( self ):
		'''Put the symbols that lost a conflict in a commented-out folder at the end
		   of the logic, grouped by the subsystem each came from.  Nothing in a
		   commented-out folder takes part in the program.
		   Depends on corrected cross references.'''
		if not self.conflictCopies:
			return
		
		symbols = self.objList[ smw.type.symbol ]
		folders = [ obj for obj in symbols if obj.SmC == smw.symType.folder ]
		logic = [ obj for obj in folders if not obj.hasKey( smw.key.parent ) ]
		if not logic:
			logging.warning( 'The program has no logic folder, so there is no %s folder.' % conflictFolderName )
			return
		like = ( [ obj for obj in folders if obj.hasKey( smw.key.parent )
			and obj.getKey( smw.key.name ) in ( '', smw.symType.folderName ) ] or [None] )[0]
		
		root = self.newFolder( like, logic[0], smw.key.byHand, [ smw.key.comment1 + '=' + conflictFolderName ] )
		groups = []		#[ subsystem it stands for, folder, copies ]
		loose = []
		for side, element in self.conflictCopies:
			copy = self.obj( element )
			source = self.findReference( smw.type.symbol, side, copy.getKey( smw.key.parent ) )
			if source is None:
				#the subsystem it was in has gone
				group = [ None, root, loose ]
			else:
				group = ( [ group for group in groups if group[0] is source ] or [None] )[0]
			if group is None:
				caption = [ key + '=' + source.getKey(key) for key in source._dataOrder if re.fullmatch( 'Cmn[0-9]+', key ) ]
				caption = caption or [ smw.key.comment1 + '=' + source.name ]
				group = [ source, self.newFolder( like, root, smw.key.propagated, caption ), [] ]
				groups.append( group )
			
			self.takeNewRef( copy )
			copy.setKey( smw.key.parent, group[1].H )
			self.commentOut( copy )
			group[2].append( copy )
		
		symbols.append( root )
		for source, folder, copies in groups:
			symbols.append( folder )
			symbols.extend( copies )
		symbols.extend( loose )
	
	def origin( self, obj ):
		'''Where an object came from: '' when it is unchanged, otherwise the side that added or changed it'''
		if obj.refs['']:
			return ''
		if obj.refs[primary]:
			return primary
		return secondary()
	
	def resolveSlotConflicts( self ):
		'''A slot holds one device.  When each side put a device in the same slot,
		   keep the primary's and remove the other with everything that belongs to it.
		   Depends on corrected cross references.'''
		devices = self.objList.get( smw.type.device, [] )
		holders = {}
		for obj in devices:
			holders.setdefault( obj.getKey( smw.key.parent ), [] ).append( obj )
		
		for slot in list(devices):
			if slot.getKey( smw.key.flag ) != smw.slotFlag:
				continue
			inSlot = holders.get( slot.H, [] )
			if len(inSlot) < 2:
				continue
			keep = ( [ obj for obj in inSlot if self.origin(obj) == primary ] or inSlot )[0]
			for obj in inSlot:
				if obj is keep:
					continue
				names = { self.origin(keep): keep.name, self.origin(obj): obj.name }
				logging.warning( 'Conflict in %s %s (%s): the slot holds %r in your file and %r in their file.  Kept %ss.'
					% ( slot.type, slot.H, slot.name, names.get('A', ''), names.get('B', ''), sideNames[self.origin(keep)] ) )
				self.removeDevice( obj )
	
	def removeDevice( self, device ):
		'''Remove a device, the devices below it and every object that belongs to them'''
		removed = self.removeTree( smw.type.device, [device] )
		handles = [ obj.H for obj in removed ]
		for list in self.objList:
			if list == smw.type.device:
				continue
			owned = [ obj for obj in self.objList[list] if obj.getKey( smw.key.DvCrossRef ) in handles ]
			self.removeTree( list, owned )
	
	def removeTree( self, list, objects ):
		'''Remove the given objects of one type along with all their descendants.  Returns what was removed.'''
		removed = []
		pending = [ obj for obj in objects ]
		while pending:
			obj = pending.pop()
			removed.append( obj )
			pending.extend( other for other in self.objList[list]
				if other.getKey( smw.key.parent ) == obj.H and not other in removed and not other in pending )
		self.objList[list] = [ obj for obj in self.objList[list] if not obj in removed ]
		return removed
	
	def compressedDevices( self ):
		'''The device objects for writing, with each run of identical empty slots back in one object'''
		out = []
		runs = {}
		for obj in self.objList[ smw.type.device ]:
			if obj.getKey( smw.key.flag ) == smw.slotFlag and not obj.hasKey( smw.key.childCount ):
				lines = str(obj).split(newline)
				alike = newline.join( line for line in lines
					if not line.split('=',1)[0] in ( smw.key.ref, smw.key.address ) )
				if alike in runs:
					runs[alike].append( obj )
					continue
				runs[alike] = [obj]
			out.append( obj )
		
		for run in runs.values():
			if len(run) > 1:
				addresses = ','.join( obj.getKey( smw.key.address ) for obj in run )
				run[0].setKey( smw.key.ref, compressHandles( [ obj.H for obj in run ] ) )
				run[0].setKey( smw.key.address, addresses )
		return out
	
	def buildForwardReference( self, ref ):
		'''Build a forward reference table, creating or updating the H values as needed'''
# 		H = 1
# 		if ref == smw.type.signal:
# 			H = self.firstSignal
			
		#unchanged objects keep their handles, then the primary's objects get theirs,
		#and the other side's objects take what is left
		byOrigin = sorted( self.objList[ref], key=lambda obj: ['', primary, secondary()].index( self.origin(obj) ) )
		for obj in byOrigin:
			#get a unique ref for this obj
			newH = self.getUniqueRef( ref, obj )
			
			#register this object with its different lists based on its original refs (for lookup)
			for file in ['', 'A', 'B']:
				if obj.refs[file]:
					logging.debug( ref +' '+ file +' '+ obj.refs[file] + ' -> ' + newH )
					self.references[ref][file][ obj.refs[file] ] = obj
			#set the new unique ref (for output)
			obj.setRef( newH )
			
			
			
		
	def buildBackReference( self, forward, back=None ):
		'''Build a back reference table for needed entries'''
		if back is None:
			back = {}
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
#		if smw.type.symbol in self.objList:
#			self.recreateParentage()
#			self.correctSymbolArrangement()
		
		for smwType in self.references:
			self.buildForwardReference( smwType )
		
		self.correctAllCrossRefs()
		self.resolveSlotConflicts()
		self.addConflictFolder()
		self.rebuildChildLists( smw.type.symbol )
		self.rebuildChildLists( smw.type.device )
		
		global signalBackTable
		signalBackTable = self.buildBackReference( self.references[smw.type.signal][''] )
		signalBackTable = self.buildBackReference( self.references[smw.type.signal]['A'], signalBackTable )
		signalBackTable = self.buildBackReference( self.references[smw.type.signal]['B'], signalBackTable )
		# Re-encode the signal references in the symbol objects
		#signalBackTable = self.references[ 'back-' + smw.type.signal ]
		
		#One side may have renamed a signal that the other side still uses under
		#its old name.  The old name then means the signal that now has its handle.
		#Or one side may have dropped a signal that the other side has a new use
		#for.  It is put back, and is only written if something does use it.
		for name, signal in baseSignals.items():
			if name in signalBackTable:
				continue
			for side in ( primary, secondary() ):
				renamed = self.references[smw.type.signal][side].get( signal.H )
				if renamed:
					signalBackTable[name] = renamed
					break
			else:
				restored = self.obj( str(signal) )
				restored.hidden = True
				self.objList[smw.type.signal].append( restored )
				restored.setRef( self.getUniqueRef( smw.type.signal, restored ) )
				signalBackTable[name] = restored
		
		if smw.type.symbol in self.objList:
			for obj in self.objList[ smw.type.symbol ]:
				obj.fixSignals(signalBackTable)

	
	
	def __str__(self):
		out = []
		#step through all objects and add
		for objType in self.objOrder:
			objects = self.objList[objType]
			if objType == smw.type.device:
				objects = self.compressedDevices()
			for obj in objects:
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
        # newline='' keeps the CRLF line ends exactly as they are in the file
        with open(filename, 'r', encoding=file_encoding, newline='') as f:
            return f.readlines()
    except IOError:
        print("can't open file '" + filename + "'. aborting.")
        sys.exit(-1)

		
def merge():
	global ai, bi, xi
	global result, oresult, conflict
	
	result = []
	oresult = {}
	conflict = False
	objResult = []
	copies = []
	mergeHandler = smw.merge['unknown']
	
	for objType in masterObjOrder:
		try:
			mergeHandler = smw.merge[objType]
		except KeyError:
			mergeHandler = smw.merge['unknown']
			logging.info( 'Unhandled merge object: '+objType+'.  Using Conservative SMW merge.')

		if mergeHandler:
			objResult = mergeHandler( ai.diffOut(objType), bi.diffOut(objType), xi.diffOut(objType) )
			oresult[objType] = objResult
			logging.info( objType + ' - conflict: ' + str(objResult.conflict) ) 
			if objResult.conflict:
				conflict = True
		
			result.extend(objResult)
			copies.extend( getattr( objResult, 'conflictCopies', [] ) )
		
	logging.info('conflict = ' + str(conflict))
	
	for signal in xi.references[ smw.type.signal ].values():
		baseSignals[ signal.name ] = signal
	
	global o
	o = outFile(result, copies)
	
	if options.output_file:
		f = open(options.output_file, 'w', encoding=file_encoding, newline='')
		f.write(str(o))
		f.write(newline)
		f.close()
	else:
		# write through the byte stream so the CRLF line ends are not translated
		sys.stdout.buffer.write( (str(o) + newline).encode(file_encoding) )

def main():	
	parser = OptionParser(usage="usage: %prog [options] your-file their-file original-file",
							version="%prog " + version, 
							description=program_description,
							epilog=copyright)
	parser.add_option("-o", "--output-file", dest="output_file",
						help="write result to FILE instead of stdout", metavar="FILE")
	parser.add_option('-l', '--logging-level', dest="log_level", metavar="LEVEL", choices=list(LOGGING_LEVELS.keys()),
						help='Logging level.  '  'LEVEL can be "' + '", "'.join(LOGGING_LEVELS.keys()) + '"')
	parser.add_option("-f", "--log-file", dest="log_file",
						help="write debugging information to FILE", metavar="FILE")
	
	parser.add_option("-p", "--primary", dest="primary", metavar="SIDE", choices=['mine', 'theirs'], default='theirs',
						help='the file that wins when both change the same thing differently: "mine" or "theirs" (default)')
	
	parser.add_option("--no-conflict-folder", dest="conflict_folder", action="store_false", default=True,
						help='do not keep the version of a symbol that lost a conflict.  By default it is put, commented out, in a "'
							+ conflictFolderName + '" folder at the end of the logic')
	
	global options, primary, conflictFolder
	(options, args) = parser.parse_args()
	primary = {'mine': 'A', 'theirs': 'B'}[options.primary]
	conflictFolder = options.conflict_folder
	
	logging_level = LOGGING_LEVELS.get(options.log_level, logging.WARNING)
	logging.basicConfig(level=logging_level, filename=options.log_file,
						  format='%(asctime)s %(levelname)s: %(message)s',
						  datefmt='%Y-%m-%d %H:%M:%S')
	
	if len(args) > 2:
		global af, bf, xf
		af = "".join(read_file(args[0]))
		bf = "".join(read_file(args[1]))
		xf = "".join(read_file(args[2]))
		global ai, bi, xi
		ai = inFile(af)
		bi = inFile(bf)
		xi = inFile(xf)
		
		merge()
	else:
		parser.print_help()


if __name__ == '__main__':
	main()
