import numpy
from generated.array import Array
from generated.base_struct import BaseStruct
from generated.formats.base.basic import Float


class WeirdElementTwo(BaseStruct):

	__name__ = 'WeirdElementTwo'

	_import_key = 'manis.compounds.WeirdElementTwo'

	def __init__(self, context, arg=0, template=None, set_default=True):
		super().__init__(context, arg, template, set_default=False)
		self.many_floats = Array(self.context, 0, None, (0,), Float)
		if set_default:
			self.set_defaults()

	_attribute_list = BaseStruct._attribute_list + [
		('many_floats', Array, (0, None, (7,), Float), (False, None), None),
		]

	@classmethod
	def _get_filtered_attribute_list(cls, instance, include_abstract=True):
		yield from super()._get_filtered_attribute_list(instance, include_abstract)
		yield 'many_floats', Array, (0, None, (7,), Float), (False, None)