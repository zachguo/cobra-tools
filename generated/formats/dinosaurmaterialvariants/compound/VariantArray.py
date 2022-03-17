import numpy
import typing
from generated.array import Array
from generated.context import ContextReference
from generated.formats.dinosaurmaterialvariants.compound.Variant import Variant


class VariantArray:

	context = ContextReference()

	def __init__(self, context, arg=None, template=None):
		self.name = ''
		self._context = context
		self.arg = arg
		self.template = template
		self.io_size = 0
		self.io_start = 0
		self.variants = Array(self.context)
		self.set_defaults()

	def set_defaults(self):
		self.variants = Array(self.context)

	def read(self, stream):
		self.io_start = stream.tell()
		self.variants.read(stream, Variant, self.arg, None)

		self.io_size = stream.tell() - self.io_start

	def write(self, stream):
		self.io_start = stream.tell()
		self.variants.write(stream, Variant, self.arg, None)

		self.io_size = stream.tell() - self.io_start

	def get_info_str(self):
		return f'VariantArray [Size: {self.io_size}, Address: {self.io_start}] {self.name}'

	def get_fields_str(self):
		s = ''
		s += f'\n	* variants = {self.variants.__repr__()}'
		return s

	def __repr__(self):
		s = self.get_info_str()
		s += self.get_fields_str()
		s += '\n'
		return s