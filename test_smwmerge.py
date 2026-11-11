"""Tests for smwmerge.py.  Run with:  python3 -m pytest

The merges run the real command line program on two real SIMPL Windows
programs.  Those programs are not part of the repository.  Put them next to
this file, or name their folder in SMW_TEST_PROGRAMS.  The tests that need
them are skipped when they are not there.
"""

import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'smwmerge.py')
PROGRAMS = os.environ.get('SMW_TEST_PROGRAMS', HERE)
FUSION = os.path.join(PROGRAMS, 'fusion_demo_3_series_mc3.smw')
SMART_GRAPHICS = os.path.join(PROGRAMS, 'Smart_Graphics_RL_Sample_rev2.1.smw')
REAL_FILES = [FUSION, SMART_GRAPHICS]


def standalone(test):
	'''Mark a test that does not use the real programs.'''
	test.standalone = True
	return test


@pytest.fixture(autouse=True)
def real_programs(request):
	missing = [os.path.basename(path) for path in REAL_FILES if not os.path.exists(path)]
	if missing and not getattr(request.function, 'standalone', False):
		pytest.skip('needs ' + ' and '.join(missing) + ' in ' + PROGRAMS)

CRLF = '\r\n'
ENCODING = 'latin-1'


########################################################
##   Helpers
########################################################

class Program:
	'''A SMW file as a list of blocks, each block a list of [key, value] pairs.'''

	def __init__(self, text):
		self.blocks = []
		for chunk in text.split(CRLF + ']' + CRLF):
			if not chunk:
				continue
			lines = chunk.split(CRLF)
			assert lines[0] == '['
			self.blocks.append([line.split('=', 1) for line in lines[1:]])

	@classmethod
	def load(cls, path):
		with open(path, encoding=ENCODING, newline='') as f:
			return cls(f.read())

	def text(self):
		out = []
		for block in self.blocks:
			out.append('[' + CRLF)
			for key, value in block:
				out.append(key + '=' + value + CRLF)
			out.append(']' + CRLF)
		return ''.join(out)

	def save(self, path):
		with open(path, 'w', encoding=ENCODING, newline='') as f:
			f.write(self.text())
		return str(path)

	def find(self, **match):
		'''Return the blocks whose keys have the given values.'''
		found = []
		for block in self.blocks:
			keys = dict(block)
			if all(keys.get(k) == v for k, v in match.items()):
				found.append(block)
		return found

	def one(self, **match):
		found = self.find(**match)
		assert len(found) == 1, (match, len(found))
		return found[0]


def get(block, key):
	return dict(block)[key]


def put(block, key, value):
	'''Set a key in a block, adding it at the end when it is new.'''
	for pair in block:
		if pair[0] == key:
			pair[1] = value
			return
	block.append([key, value])


def run(*args, cwd=None):
	# no display, so that nothing the program does can open a window during the tests
	env = {k: v for k, v in os.environ.items() if k not in ('DISPLAY', 'WAYLAND_DISPLAY')}
	return subprocess.run([sys.executable, SCRIPT] + [str(a) for a in args],
		cwd=cwd, capture_output=True, env=env, timeout=120)


def merged_text(mine, theirs, base, *options, cwd=None):
	'''Merge three files and return the result, failing on any error.'''
	result = run(mine, theirs, base, *options, cwd=cwd)
	assert result.returncode == 0, result.stderr.decode(ENCODING)
	return result.stdout.decode(ENCODING), result.stderr.decode(ENCODING)


########################################################
##   One-sided edits used by several tests
########################################################

def rename_folder(program):
	put(program.one(ObjTp='Sm', H='4'), 'Cmn1', 'Renamed Subsystem')

def change_device(program):
	put(program.one(ObjTp='Dv', H='3'), 'Nm', 'Fixed Slot')

def change_symbol_parameter(program):
	symbol = [b for b in program.find(ObjTp='Sm') if 'P1' in dict(b) and 'PrH' in dict(b)][0]
	put(symbol, 'P1', get(symbol, 'P1') + 'x')

def rename_signal(program):
	put(program.one(ObjTp='Sg', H='4'), 'Nm', 'startup_renamed')

def append_block(program, block):
	'''Add a block after the last one of its type, with the next free handle.  Returns the handle.'''
	same_type = program.find(ObjTp=get(block, 'ObjTp'))
	handle = str(max(int(get(b, 'H')) for b in same_type) + 1)
	put(block, 'H', handle)
	program.blocks.insert(program.blocks.index(same_type[-1]) + 1, block)
	return handle

def add_symbol(program, name='Added Symbol', signal_name='added_signal', folder='20'):
	'''Add a symbol to a folder, driving a new signal from the existing signal 4.'''
	signal = append_block(program, [['ObjTp', 'Sg'], ['H', ''], ['Nm', signal_name]])
	symbol = append_block(program, [['ObjTp', 'Sm'], ['H', ''], ['SmC', '5'], ['Nm', name],
		['ObjVer', '1'], ['PrH', folder], ['CF', '2'], ['n1I', '1'], ['n1O', '1'],
		['mI', '1'], ['I1', '4'], ['mO', '1'], ['tO', '1'], ['O1', signal]])
	parent = program.one(ObjTp='Sm', H=folder)
	count = int(get(parent, 'mC')) + 1
	put(parent, 'mC', str(count))
	put(parent, 'C' + str(count), symbol)
	return symbol

def delete_symbol(program, handle='21'):
	'''Remove a symbol and take it out of its parent's list of children.'''
	symbol = program.one(ObjTp='Sm', H=handle)
	parent = program.one(ObjTp='Sm', H=get(symbol, 'PrH'))
	program.blocks.remove(symbol)
	children = [pair[1] for pair in parent if pair[0][0] == 'C' and pair[0][1:].isdigit()]
	children.remove(handle)
	position = parent.index(['C1', get(parent, 'C1')])
	parent[:] = [pair for pair in parent if not (pair[0][0] == 'C' and pair[0][1:].isdigit())]
	for number, child in enumerate(children, 1):
		parent.insert(position + number - 1, ['C' + str(number), child])
	put(parent, 'mC', str(len(children)))

def remove_unused_signals(program):
	'''Take out the signals that no symbol is connected to.  A merge does not write those.'''
	used = set()
	for symbol in program.find(ObjTp='Sm'):
		used.update(pair[1] for pair in symbol if pair[0][0] in 'IO' and pair[0][1:].isdigit())
	program.blocks = [b for b in program.blocks if dict(b).get('ObjTp') != 'Sg' or get(b, 'H') in used]

ONE_SIDED_EDITS = [rename_folder, change_device, change_symbol_parameter, rename_signal, add_symbol, delete_symbol]


########################################################
##   Baseline behaviour
########################################################

def test_helper_reproduces_real_files_exactly():
	for path in REAL_FILES:
		with open(path, encoding=ENCODING, newline='') as f:
			assert Program.load(path).text() == f.read()


@pytest.mark.parametrize('path', REAL_FILES, ids=os.path.basename)
def test_merging_a_file_with_itself_returns_it_unchanged(path):
	result = run(path, path, path)
	with open(path, 'rb') as f:
		assert result.stdout == f.read()


########################################################
##   -o / --output-file
########################################################

def test_output_file_option_after_the_file_names(tmp_path):
	out = tmp_path / 'merged.smw'
	result = run(FUSION, FUSION, FUSION, '-o', out, cwd=tmp_path)
	assert result.returncode == 0, result.stderr.decode(ENCODING)
	with open(FUSION, 'rb') as f:
		assert out.read_bytes() == f.read()
	assert os.listdir(tmp_path) == ['merged.smw']
	assert result.stdout == b''


def test_output_file_option_before_the_file_names(tmp_path):
	out = tmp_path / 'merged.smw'
	result = run('-o', out, FUSION, FUSION, FUSION, cwd=tmp_path)
	assert result.returncode == 0, result.stderr.decode(ENCODING)
	with open(FUSION, 'rb') as f:
		assert out.read_bytes() == f.read()


########################################################
##   Logging
########################################################

def test_nothing_is_logged_by_default_on_a_clean_merge():
	result = run(FUSION, FUSION, FUSION)
	assert result.stderr == b''


########################################################
##   Program information (FSgntr) changed on both sides
########################################################

def test_program_info_changed_on_both_sides_keeps_the_highest_values(tmp_path):
	base = Program.load(FUSION)
	mine = Program.load(FUSION)
	theirs = Program.load(FUSION)
	# MinTIOVrs 650 -> 700 / 1000, SavedBy SMW4.02.18 -> SMW4.02.30 / SMW4.03.00
	put(mine.one(ObjTp='FSgntr'), 'MinTIOVrs', '700')
	put(mine.one(ObjTp='FSgntr'), 'SavedBy', 'SMW4.03.00')
	put(theirs.one(ObjTp='FSgntr'), 'MinTIOVrs', '1000')
	put(theirs.one(ObjTp='FSgntr'), 'SavedBy', 'SMW4.02.30')

	text, _ = merged_text(mine.save(tmp_path / 'mine.smw'),
		theirs.save(tmp_path / 'theirs.smw'), base.save(tmp_path / 'base.smw'))

	expected = Program.load(FUSION)
	put(expected.one(ObjTp='FSgntr'), 'MinTIOVrs', '1000')
	put(expected.one(ObjTp='FSgntr'), 'SavedBy', 'SMW4.03.00')
	assert text == expected.text()


########################################################
##   A change made on only one side must come through untouched
########################################################

@pytest.mark.parametrize('edit', ONE_SIDED_EDITS, ids=lambda e: e.__name__)
@pytest.mark.parametrize('side', ['mine', 'theirs'])
def test_change_on_one_side_gives_that_sides_file(tmp_path, edit, side):
	base = Program.load(FUSION)
	changed = Program.load(FUSION)
	edit(changed)
	assert changed.text() != base.text()
	base_path = base.save(tmp_path / 'base.smw')
	changed_path = changed.save(tmp_path / 'changed.smw')

	if side == 'mine':
		text, log = merged_text(changed_path, base_path, base_path)
	else:
		text, log = merged_text(base_path, changed_path, base_path)

	assert text == changed.text()
	assert log == ''


########################################################
##   References
########################################################

def test_reference_to_a_symbol_that_does_not_exist_is_reported(tmp_path):
	program = Program.load(FUSION)
	# there is no symbol 698, although there is a device with that handle
	assert program.find(ObjTp='Sm', H='698') == []
	assert len(program.find(ObjTp='Dv', H='698')) == 1
	put(program.one(ObjTp='Sm', H='21'), 'PrH', '698')
	path = program.save(tmp_path / 'broken.smw')

	result = run(path, path, path)

	assert b'Could not find key in references.  obj=Sm 21 -> Sm () 698' in result.stderr


########################################################
##   Changes on both sides
########################################################

def test_symbols_added_to_the_same_folder_on_both_sides_are_both_kept(tmp_path):
	base = Program.load(FUSION)
	mine = Program.load(FUSION)
	theirs = Program.load(FUSION)
	add_symbol(mine, 'My Symbol', 'my_signal')
	add_symbol(theirs, 'Their Symbol', 'their_signal')

	text, log = merged_text(mine.save(tmp_path / 'mine.smw'),
		theirs.save(tmp_path / 'theirs.smw'), base.save(tmp_path / 'base.smw'))

	# the same as making both additions to one file, the primary's (theirs) first
	expected = Program.load(FUSION)
	add_symbol(expected, 'Their Symbol', 'their_signal')
	add_symbol(expected, 'My Symbol', 'my_signal')
	assert text == expected.text()
	assert log == ''


def test_symbol_deleted_on_one_side_and_another_added_to_the_same_folder_on_the_other(tmp_path):
	base = Program.load(FUSION)
	mine = Program.load(FUSION)
	theirs = Program.load(FUSION)
	delete_symbol(mine, '21')
	add_symbol(theirs, 'Their Symbol', 'their_signal', folder='20')

	text, log = merged_text(mine.save(tmp_path / 'mine.smw'),
		theirs.save(tmp_path / 'theirs.smw'), base.save(tmp_path / 'base.smw'))

	expected = Program.load(FUSION)
	delete_symbol(expected, '21')
	add_symbol(expected, 'Their Symbol', 'their_signal', folder='20')
	assert text == expected.text()
	assert log == ''


########################################################
##   Building more than one output in a process
########################################################

@standalone
def test_signal_names_do_not_carry_over_from_an_earlier_output():
	import smwmerge
	signal = CRLF.join(['[', 'ObjTp=Sg', 'H=4', 'Nm=only_in_first']) + CRLF + ']' + CRLF
	symbol = CRLF.join(['[', 'ObjTp=Sm', 'H=1', 'SmC=5', 'Nm=Uses It', 'mI=1', 'I1=only_in_first']) + CRLF + ']' + CRLF
	other_signal = signal.replace('only_in_first', 'only_in_second')
	smwmerge.outFile(signal)

	# this output has no signal of that name, so the symbol cannot be resolved
	with pytest.raises(KeyError, match='only_in_first'):
		smwmerge.outFile(other_signal + symbol)


########################################################
##   The same object changed on both sides
########################################################

def three_programs(tmp_path, my_edit, their_edit):
	'''Save a base, a copy with my edit and a copy with their edit.  Returns the three paths.'''
	base = Program.load(FUSION)
	mine = Program.load(FUSION)
	theirs = Program.load(FUSION)
	my_edit(mine)
	their_edit(theirs)
	return (mine.save(tmp_path / 'mine.smw'), theirs.save(tmp_path / 'theirs.smw'),
		base.save(tmp_path / 'base.smw'))


def set_key(object_type, handle, key, value):
	def edit(program):
		put(program.one(ObjTp=object_type, H=handle), key, value)
	return edit


def test_different_keys_of_one_symbol_changed_on_each_side_are_both_kept(tmp_path):
	# symbol 21 is a One Shot: I change its time parameter, they change its comment
	mine, theirs, base = three_programs(tmp_path,
		set_key('Sm', '21', 'P1', '.75s'), set_key('Sm', '21', 'Cmn1', 'Their comment'))

	text, log = merged_text(mine, theirs, base)

	expected = Program.load(FUSION)
	put(expected.one(ObjTp='Sm', H='21'), 'P1', '.75s')
	put(expected.one(ObjTp='Sm', H='21'), 'Cmn1', 'Their comment')
	assert text == expected.text()
	assert log == ''


def test_same_key_changed_on_both_sides_takes_theirs_by_default(tmp_path):
	mine, theirs, base = three_programs(tmp_path,
		set_key('Sm', '21', 'P1', '.75s'), set_key('Sm', '21', 'P1', '.25s'))

	text, log = merged_text(mine, theirs, base, '--no-conflict-folder')

	expected = Program.load(FUSION)
	put(expected.one(ObjTp='Sm', H='21'), 'P1', '.25s')
	assert text == expected.text()


def test_same_key_changed_on_both_sides_takes_mine_when_mine_is_primary(tmp_path):
	mine, theirs, base = three_programs(tmp_path,
		set_key('Sm', '21', 'P1', '.75s'), set_key('Sm', '21', 'P1', '.25s'))

	text, log = merged_text(mine, theirs, base, '--primary', 'mine', '--no-conflict-folder')

	expected = Program.load(FUSION)
	put(expected.one(ObjTp='Sm', H='21'), 'P1', '.75s')
	assert text == expected.text()


def test_same_key_changed_on_both_sides_says_what_was_discarded(tmp_path):
	mine, theirs, base = three_programs(tmp_path,
		set_key('Sm', '21', 'P1', '.75s'), set_key('Sm', '21', 'P1', '.25s'))

	text, log = merged_text(mine, theirs, base)

	assert "Conflict in Sm 21 (One Shot): P1 is '.75s' in your file and '.25s' in their file.  Kept theirs." in log


def test_log_names_the_object_type_that_had_a_conflict(tmp_path):
	mine, theirs, base = three_programs(tmp_path,
		set_key('Sm', '21', 'P1', '.75s'), set_key('Sm', '21', 'P1', '.25s'))

	text, log = merged_text(mine, theirs, base, '-l', 'info')

	assert 'Sm - conflict: True' in log
	assert 'Sg - conflict: False' in log
	assert 'Dv - conflict: False' in log


def test_symbol_replaced_by_a_different_one_on_each_side_keeps_both(tmp_path):
	def replace_with(name, signal_name):
		def edit(program):
			delete_symbol(program, '21')
			add_symbol(program, name, signal_name)
		return edit
	mine, theirs, base = three_programs(tmp_path,
		replace_with('My Symbol', 'my_signal'), replace_with('Their Symbol', 'their_signal'))

	text, log = merged_text(mine, theirs, base)

	expected = Program.load(FUSION)
	delete_symbol(expected, '21')
	add_symbol(expected, 'Their Symbol', 'their_signal')
	add_symbol(expected, 'My Symbol', 'my_signal')
	assert text == expected.text()
	assert log == ''


@standalone
def test_symbol_replaced_in_place_by_a_different_one_on_each_side_keeps_both(monkeypatch):
	monkeypatch.delenv('DISPLAY', raising=False)
	monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
	import smwmerge
	def symbol(handle, name):
		return CRLF.join(['[', 'ObjTp=Sm', 'H=' + handle, 'SmC=5', 'Nm=' + name, ']'])
	kept, old = symbol('1', 'Kept'), symbol('2', 'Old')

	result = smwmerge.MergeSymbols([kept, symbol('3', 'Mine')], [kept, symbol('3', 'Theirs')], [kept, old])

	names = [line for text in result for line in text.split(CRLF) if line.startswith('Nm=')]
	# the primary's (theirs) comes first
	assert names == ['Nm=Kept', 'Nm=Theirs', 'Nm=Mine']


########################################################
##   Hardware
########################################################

def expand_handles(text):
	'''"7.9,12" -> ['7', '8', '9', '12']'''
	handles = []
	for part in text.split(','):
		first, _, last = part.partition('.')
		handles.extend(str(h) for h in range(int(first), int(last or first) + 1))
	return handles


def compress_handles(handles):
	'''['7', '8', '9', '12'] -> "7.9,12"'''
	runs = []
	for handle in (int(h) for h in handles):
		if runs and runs[-1][1] == handle - 1:
			runs[-1][1] = handle
		else:
			runs.append([handle, handle])
	return ','.join(str(a) if a == b else '%d.%d' % (a, b) for a, b in runs)


def add_device(program, slot, name):
	'''Put a device in an empty Cresnet slot of the Smart Graphics program, the way
	the two devices already in that program are stored.'''
	devices = program.find(ObjTp='Dv')
	handle = str(max(int(h) for b in devices for h in expand_handles(get(b, 'H'))) + 1)

	# the records that belong to the device
	database = append_block(program, [['ObjTp', 'Db'], ['H', ''], ['DvH', handle], ['Whc', '3'], ['Mnf', 'Crestron'], ['Mdl', name]])
	sheet = append_block(program, [['ObjTp', 'Cs'], ['H', ''], ['DvH', handle]])
	ethernet = append_block(program, [['ObjTp', 'Et'], ['H', ''], ['DvH', handle], ['IPM', '255.255.255.0'], ['IPA', '127.0.0.1']])
	symbol = append_block(program, [['ObjTp', 'Sm'], ['H', ''], ['SmC', '3553'], ['Nm', name], ['ObjVer', '1'],
		['DvH', handle], ['PrH', '6'], ['CF', '2'], ['Cmn1', name]])
	parent = program.one(ObjTp='Sm', H='6')
	count = int(get(parent, 'mC')) + 1
	put(parent, 'mC', str(count))
	put(parent, 'C' + str(count), symbol)

	# take the slot out of the record that holds the run of empty slots
	empty = [b for b in devices if slot in expand_handles(get(b, 'H')) and get(b, 'H') != slot][0]
	handles = expand_handles(get(empty, 'H'))
	addresses = get(empty, 'Ad').split(',')
	address = addresses.pop(handles.index(slot))
	handles.remove(slot)
	put(empty, 'H', compress_handles(handles))
	put(empty, 'Ad', ','.join(addresses))

	# the slot gets a record of its own, after the other slots of the same parent
	own = [list(pair) for pair in empty]
	put(own, 'H', slot)
	put(own, 'Ad', address)
	own.extend([['mC', '1'], ['C1', handle]])
	position = program.blocks.index(empty) + 1
	while get(program.blocks[position], 'PrH') == get(empty, 'PrH'):
		position += 1
	program.blocks.insert(position, own)

	program.blocks.insert(program.blocks.index(devices[-1]) + 1, [['ObjTp', 'Dv'], ['Nm', name], ['H', handle],
		['PrH', slot], ['DvC', '3040'], ['ObjVer', '1'], ['Ad', address], ['SmH', symbol], ['RelStat', 'Release'],
		['ProdLine', 'Shades/Drapes'], ['DbH', database], ['CsH', sheet], ['EtH', ethernet]])


def hardware_programs(tmp_path, my_edit, their_edit):
	base = Program.load(SMART_GRAPHICS)
	mine = Program.load(SMART_GRAPHICS)
	theirs = Program.load(SMART_GRAPHICS)
	my_edit(mine)
	their_edit(theirs)
	return (mine.save(tmp_path / 'mine.smw'), theirs.save(tmp_path / 'theirs.smw'),
		base.save(tmp_path / 'base.smw'))


@pytest.mark.parametrize('side', ['mine', 'theirs'])
def test_device_added_on_one_side_gives_that_sides_file(tmp_path, side):
	edit = lambda program: add_device(program, '40', 'Added Device')
	nothing = lambda program: None
	if side == 'mine':
		mine, theirs, base = hardware_programs(tmp_path, edit, nothing)
	else:
		mine, theirs, base = hardware_programs(tmp_path, nothing, edit)

	text, log = merged_text(mine, theirs, base)

	expected = Program.load(SMART_GRAPHICS)
	edit(expected)
	assert text == expected.text()
	assert log == ''


def test_devices_added_in_different_slots_on_each_side_are_both_kept(tmp_path):
	mine, theirs, base = hardware_programs(tmp_path,
		lambda program: add_device(program, '40', 'My Device'),
		lambda program: add_device(program, '41', 'Their Device'))

	text, log = merged_text(mine, theirs, base)

	# their file is the primary, so their device keeps its handles and mine follows
	expected = Program.load(SMART_GRAPHICS)
	add_device(expected, '41', 'Their Device')
	add_device(expected, '40', 'My Device')
	assert Program(text).find(ObjTp='Dv', Nm='My Device') == expected.find(ObjTp='Dv', Nm='My Device')
	assert Program(text).find(ObjTp='Dv', Nm='Their Device') == expected.find(ObjTp='Dv', Nm='Their Device')
	assert sorted(map(str, Program(text).blocks)) == sorted(map(str, expected.blocks))
	assert log == ''


def test_devices_added_in_the_same_slot_on_each_side_keeps_only_theirs_by_default(tmp_path):
	mine, theirs, base = hardware_programs(tmp_path,
		lambda program: add_device(program, '40', 'My Device'),
		lambda program: add_device(program, '40', 'Their Device'))

	text, log = merged_text(mine, theirs, base)

	with open(theirs, encoding=ENCODING, newline='') as f:
		assert text == f.read()
	assert "Conflict in Dv 40 (P3Cresnet): the slot holds 'My Device' in your file and 'Their Device' in their file.  Kept theirs." in log


def test_devices_added_in_the_same_slot_on_each_side_keeps_only_mine_when_mine_is_primary(tmp_path):
	mine, theirs, base = hardware_programs(tmp_path,
		lambda program: add_device(program, '40', 'My Device'),
		lambda program: add_device(program, '40', 'Their Device'))

	text, log = merged_text(mine, theirs, base, '--primary', 'mine')

	with open(mine, encoding=ENCODING, newline='') as f:
		assert text == f.read()


def test_new_signal_with_the_same_name_on_both_sides_is_one_signal(tmp_path):
	mine, theirs, base = three_programs(tmp_path,
		lambda program: add_symbol(program, 'My Symbol', 'shared_signal'),
		lambda program: add_symbol(program, 'Their Symbol', 'shared_signal'))

	text, log = merged_text(mine, theirs, base)

	merged = Program(text)
	signal = merged.one(ObjTp='Sg', Nm='shared_signal')
	assert get(merged.one(ObjTp='Sm', Nm='My Symbol'), 'O1') == get(signal, 'H')
	assert get(merged.one(ObjTp='Sm', Nm='Their Symbol'), 'O1') == get(signal, 'H')
	assert log == ''


def test_signal_renamed_on_one_side_and_given_a_new_use_on_the_other(tmp_path):
	# their new symbol reads signal 4 under its old name; I renamed that signal
	mine, theirs, base = three_programs(tmp_path,
		rename_signal, lambda program: add_symbol(program, 'Their Symbol', 'their_signal'))

	text, log = merged_text(mine, theirs, base)

	expected = Program.load(FUSION)
	rename_signal(expected)
	add_symbol(expected, 'Their Symbol', 'their_signal')
	assert text == expected.text()
	assert log == ''


def test_signal_dropped_on_one_side_and_given_a_new_use_on_the_other(tmp_path):
	# signal 923 is used only by symbol 37
	def drop_the_only_user(program):
		delete_symbol(program, '37')
		program.blocks.remove(program.one(ObjTp='Sg', H='923'))
	def use_it_again(program):
		symbol = add_symbol(program, 'Their Symbol', 'their_signal')
		put(program.one(ObjTp='Sm', H=symbol), 'I1', '923')
	mine, theirs, base = three_programs(tmp_path, drop_the_only_user, use_it_again)

	text, log = merged_text(mine, theirs, base)

	# the symbol is gone, and the signal stays because it is still used
	expected = Program.load(FUSION)
	delete_symbol(expected, '37')
	use_it_again(expected)
	remove_unused_signals(expected)
	assert sorted(map(str, Program(text).blocks)) == sorted(map(str, expected.blocks))
	assert log == ''


########################################################
##   Malformed input
########################################################

def device_with_handles(handles, addresses='01,02'):
	return CRLF.join(['[', 'ObjTp=Dv', 'Nm=Not_Used', 'H=' + handles, 'PrH=4', 'DvF=Sl', 'Ad=' + addresses])


@standalone
def test_handle_range_that_does_not_match_its_addresses_is_not_expanded():
	import tracemalloc
	import smwmerge
	# two addresses, but a range that claims two million slots
	chunk = device_with_handles('1.2000000')

	tracemalloc.start()
	result = smwmerge.expandDeviceRanges(chunk)
	peak = tracemalloc.get_traced_memory()[1]
	tracemalloc.stop()

	assert result == [chunk]
	assert peak < 1000000


@standalone
@pytest.mark.parametrize('handles', ['9.7', '7.x', '7..9', 'abc,def'])
def test_handle_range_that_makes_no_sense_is_left_alone(handles):
	import smwmerge
	chunk = device_with_handles(handles)

	assert smwmerge.expandDeviceRanges(chunk) == [chunk]


########################################################
##   The conflict folder
########################################################

FOLDER_NAME = 'Merge Conflicts'
MINE_SAYS = set_key('Sm', '21', 'P1', '.75s')
THEIRS_SAYS = set_key('Sm', '21', 'P1', '.25s')

def both(*edits):
	def edit(program):
		for each in edits:
			each(program)
	return edit

def children(block):
	return [pair[1] for pair in block if pair[0][0] == 'C' and pair[0][1:].isdigit()]

def key_names(block):
	return [pair[0] for pair in block]

def merged_program(tmp_path, my_edit, their_edit, *options):
	mine, theirs, base = three_programs(tmp_path, my_edit, their_edit)
	text, log = merged_text(mine, theirs, base, *options)
	return Program(text), log

def conflict_roots(program):
	return [b for b in program.find(ObjTp='Sm', SmC='156') if dict(b).get('Cmn1') == FOLDER_NAME]

def conflict_folder(program):
	'''The conflict folder, and its sub-folders as {caption: [copies]}'''
	roots = conflict_roots(program)
	assert len(roots) == 1
	groups = {}
	for handle in children(roots[0]):
		group = program.one(ObjTp='Sm', H=handle)
		groups[get(group, 'Cmn1')] = [program.one(ObjTp='Sm', H=child) for child in children(group)]
	return roots[0], groups

def without_conflict_folder(program):
	'''Take the conflict folder and everything in it back out'''
	root, groups = conflict_folder(program)
	for handle in children(root):
		group = program.one(ObjTp='Sm', H=handle)
		for child in children(group):
			program.blocks.remove(program.one(ObjTp='Sm', H=child))
		program.blocks.remove(group)
	delete_symbol(program, get(root, 'H'))
	return program

def caption(handle):
	return get(Program.load(FUSION).one(ObjTp='Sm', H=handle), 'Cmn1')

def assert_consistent(program):
	'''Handles are unique, and each parent lists exactly the symbols that name it'''
	symbols = program.find(ObjTp='Sm')
	handles = [get(b, 'H') for b in symbols]
	assert len(handles) == len(set(handles))
	listed = {}
	for block in symbols:
		kids = children(block)
		if 'mC' in dict(block):
			assert get(block, 'mC') == str(len(kids))
		for kid in kids:
			assert kid in handles
			assert not kid in listed
			listed[kid] = get(block, 'H')
			if dict(block).get('OpF') == '0':
				assert dict(program.one(ObjTp='Sm', H=kid)).get('OpF') == '0'
	for block in symbols:
		if 'PrH' in dict(block):
			assert listed[get(block, 'H')] == get(block, 'PrH')


def test_conflict_makes_a_commented_out_folder_at_the_end_of_the_logic(tmp_path):
	result, log = merged_program(tmp_path, MINE_SAYS, THEIRS_SAYS)

	root, groups = conflict_folder(result)
	logic = result.one(ObjTp='Sm', H='4')
	assert get(root, 'PrH') == '4'
	assert children(logic)[-1] == get(root, 'H')
	assert get(logic, 'mC') == '11'
	# laid out like the subsystems already in the program, and commented out by hand
	assert key_names(root) == ['ObjTp', 'H', 'SmC', 'Nm', 'ObjVer', 'PrH', 'CF', 'OpF', 'HandF', 'Cmn1', 'mC', 'C1']
	existing = result.one(ObjTp='Sm', H='20')
	assert [get(root, key) for key in ('Nm', 'ObjVer', 'CF')] == [get(existing, key) for key in ('Nm', 'ObjVer', 'CF')]
	assert (get(root, 'OpF'), get(root, 'HandF')) == ('0', '1')


def test_conflict_copies_are_grouped_by_the_subsystem_they_came_from(tmp_path):
	result, log = merged_program(tmp_path, MINE_SAYS, THEIRS_SAYS)

	root, groups = conflict_folder(result)
	assert list(groups) == [caption('20')]
	group = result.one(ObjTp='Sm', H=children(root)[0])
	assert key_names(group) == ['ObjTp', 'H', 'SmC', 'Nm', 'ObjVer', 'PrH', 'CF', 'OpF', 'PropF', 'Cmn1', 'mC', 'C1']
	assert (get(group, 'PrH'), get(group, 'OpF'), get(group, 'PropF')) == (get(root, 'H'), '0', '1')


def test_conflict_copy_is_the_other_sides_whole_symbol_commented_out(tmp_path):
	result, log = merged_program(tmp_path, MINE_SAYS, THEIRS_SAYS)

	root, groups = conflict_folder(result)
	[copy] = groups[caption('20')]
	group = result.one(ObjTp='Sm', H=children(root)[0])
	mine = Program.load(FUSION)
	MINE_SAYS(mine)
	expected = [list(pair) for pair in mine.one(ObjTp='Sm', H='21')]
	put(expected, 'H', get(copy, 'H'))
	put(expected, 'PrH', get(group, 'H'))
	position = key_names(expected).index('n1O') + 1
	expected[position:position] = [['OpF', '0'], ['PropF', '1']]
	assert copy == expected
	assert not Program.load(FUSION).find(ObjTp='Sm', H=get(copy, 'H'))


def test_conflict_folder_changes_nothing_else(tmp_path):
	result, log = merged_program(tmp_path, MINE_SAYS, THEIRS_SAYS)

	expected = Program.load(FUSION)
	THEIRS_SAYS(expected)
	assert without_conflict_folder(result).text() == expected.text()


def test_conflict_copy_is_theirs_when_mine_is_primary(tmp_path):
	result, log = merged_program(tmp_path, MINE_SAYS, THEIRS_SAYS, '--primary', 'mine')

	root, groups = conflict_folder(result)
	[copy] = groups[caption('20')]
	assert get(copy, 'P1') == '.25s'
	assert get(result.one(ObjTp='Sm', H='21'), 'P1') == '.75s'
	assert 'Their version of Sm 21 (One Shot) is in the Merge Conflicts folder, commented out.' in log


def test_conflict_warning_says_where_the_other_version_went(tmp_path):
	result, log = merged_program(tmp_path, MINE_SAYS, THEIRS_SAYS)

	assert 'Your version of Sm 21 (One Shot) is in the Merge Conflicts folder, commented out.' in log


def test_conflicts_in_two_subsystems_get_a_group_each(tmp_path):
	result, log = merged_program(tmp_path,
		both(MINE_SAYS, set_key('Sm', '47', 'P1', 'mine')), both(THEIRS_SAYS, set_key('Sm', '47', 'P1', 'theirs')))

	root, groups = conflict_folder(result)
	assert list(groups) == [caption('20'), caption('44')]
	assert [[get(copy, 'P1') for copy in copies] for copies in groups.values()] == [['.75s'], ['mine']]
	assert_consistent(result)


def test_symbol_with_several_conflicts_is_copied_once(tmp_path):
	result, log = merged_program(tmp_path,
		both(MINE_SAYS, set_key('Sm', '21', 'Cmn1', 'My comment')), both(THEIRS_SAYS, set_key('Sm', '21', 'Cmn1', 'Their comment')))

	root, groups = conflict_folder(result)
	[copy] = groups[caption('20')]
	assert (get(copy, 'P1'), get(copy, 'Cmn1')) == ('.75s', 'My comment')
	assert log.count('is in the Merge Conflicts folder') == 1


def test_signal_used_only_by_a_conflict_copy_is_still_written(tmp_path):
	def rewire(signal_name):
		def edit(program):
			signal = append_block(program, [['ObjTp', 'Sg'], ['H', ''], ['Nm', signal_name]])
			put(program.one(ObjTp='Sm', H='21'), 'I1', signal)
		return edit

	result, log = merged_program(tmp_path, rewire('only_mine'), rewire('only_theirs'))

	root, groups = conflict_folder(result)
	[copy] = groups[caption('20')]
	assert get(copy, 'I1') == get(result.one(ObjTp='Sg', Nm='only_mine'), 'H')
	assert get(result.one(ObjTp='Sm', H='21'), 'I1') == get(result.one(ObjTp='Sg', Nm='only_theirs'), 'H')


@pytest.mark.parametrize('handle', ['20', '6'], ids=['subsystem', 'device symbol'])
def test_conflict_in_a_subsystem_or_a_device_symbol_is_not_copied(tmp_path, handle):
	result, log = merged_program(tmp_path,
		set_key('Sm', handle, 'Cmn1', 'Mine'), set_key('Sm', handle, 'Cmn1', 'Theirs'))

	assert conflict_roots(result) == []
	assert 'Conflict in Sm ' + handle in log
	assert not FOLDER_NAME in log


def test_no_conflict_folder_option_only_warns(tmp_path):
	result, log = merged_program(tmp_path, MINE_SAYS, THEIRS_SAYS, '--no-conflict-folder')

	assert conflict_roots(result) == []
	assert 'Conflict in Sm 21' in log
	assert not FOLDER_NAME in log


def test_merge_without_conflicts_has_no_conflict_folder(tmp_path):
	result, log = merged_program(tmp_path, MINE_SAYS, set_key('Sm', '47', 'P1', 'theirs'))

	assert conflict_roots(result) == []
	assert log == ''


def test_program_with_a_conflict_folder_merges_with_itself_unchanged(tmp_path):
	mine, theirs, base = three_programs(tmp_path, MINE_SAYS, THEIRS_SAYS)
	text, log = merged_text(mine, theirs, base)
	assert conflict_roots(Program(text))
	merged = Program(text).save(tmp_path / 'merged.smw')

	again, log = merged_text(merged, merged, merged)

	assert again == text
	assert log == ''


def test_symbol_changed_by_me_and_deleted_by_them_goes_to_the_conflict_folder(tmp_path):
	result, log = merged_program(tmp_path, MINE_SAYS, lambda program: delete_symbol(program, '21'))

	root, groups = conflict_folder(result)
	[copy] = groups[caption('20')]
	assert get(copy, 'P1') == '.75s'
	assert (get(copy, 'OpF'), get(copy, 'PropF')) == ('0', '1')
	assert 'Conflict in Sm 21 (One Shot): changed in your file and deleted in their file.  Kept theirs.' in log
	assert 'Your version of Sm 21 (One Shot) is in the Merge Conflicts folder, commented out.' in log
	expected = Program.load(FUSION)
	delete_symbol(expected, '21')
	assert without_conflict_folder(result).text() == expected.text()


def test_symbol_deleted_by_me_and_changed_by_them_keeps_their_change(tmp_path):
	result, log = merged_program(tmp_path, lambda program: delete_symbol(program, '21'), THEIRS_SAYS)

	assert conflict_roots(result) == []
	assert get(result.one(ObjTp='Sm', H='21'), 'P1') == '.25s'
	assert '21' in children(result.one(ObjTp='Sm', H='20'))
	assert 'Conflict in Sm 21 (One Shot): deleted in your file and changed in their file.  Kept theirs.' in log
	assert not FOLDER_NAME in log
	assert_consistent(result)


def test_symbol_deleted_by_me_and_changed_by_them_is_deleted_when_mine_is_primary(tmp_path):
	result, log = merged_program(tmp_path, lambda program: delete_symbol(program, '21'), THEIRS_SAYS, '--primary', 'mine')

	root, groups = conflict_folder(result)
	[copy] = groups[caption('20')]
	assert get(copy, 'P1') == '.25s'
	assert children(result.one(ObjTp='Sm', H='20')) == ['22']
	assert 'Conflict in Sm 21 (One Shot): deleted in your file and changed in their file.  Kept yours.' in log
	assert 'Their version of Sm 21 (One Shot) is in the Merge Conflicts folder, commented out.' in log


def test_symbol_changed_by_me_and_deleted_by_them_is_only_deleted_without_the_folder(tmp_path):
	result, log = merged_program(tmp_path, MINE_SAYS, lambda program: delete_symbol(program, '21'), '--no-conflict-folder')

	expected = Program.load(FUSION)
	delete_symbol(expected, '21')
	remove_unused_signals(expected)
	assert result.text() == expected.text()
	assert 'Conflict in Sm 21 (One Shot): changed in your file and deleted in their file.  Kept theirs.' in log
	assert not FOLDER_NAME in log


def test_changed_symbol_whose_subsystem_they_deleted_goes_straight_into_the_conflict_folder(tmp_path):
	def delete_subsystem(program):
		for handle in ('21', '22', '20'):
			delete_symbol(program, handle)

	result, log = merged_program(tmp_path, MINE_SAYS, delete_subsystem)

	[root] = conflict_roots(result)
	[copy] = [result.one(ObjTp='Sm', H=handle) for handle in children(root)]
	assert (get(copy, 'P1'), get(copy, 'OpF'), get(copy, 'PropF')) == ('.75s', '0', '1')
	assert result.find(ObjTp='Sm', H='20') == []
	assert_consistent(result)


@standalone
def test_symbol_merge_sets_aside_the_other_sides_version_of_a_conflicting_symbol(monkeypatch):
	monkeypatch.delenv('DISPLAY', raising=False)
	monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
	import smwmerge
	def symbol(parameter):
		return CRLF.join(['[', 'ObjTp=Sm', 'H=6', 'SmC=5', 'Nm=Buffer', 'PrH=4', 'P1=' + parameter, ']'])

	result = smwmerge.MergeSymbols([symbol('mine')], [symbol('theirs')], [symbol('base')])

	assert result.conflictCopies == [('A', symbol('mine'))]
