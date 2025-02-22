# Lint as: python3
# Copyright 2015 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for doc generator traversal."""

import os
import pathlib
import sys
import tempfile
import textwrap

from absl import flags
from absl.testing import absltest

from tensorflow_docs.api_generator import config
from tensorflow_docs.api_generator import doc_controls
from tensorflow_docs.api_generator import generate_lib
from tensorflow_docs.api_generator import parser

import yaml

FLAGS = flags.FLAGS


def deprecated(func):
  return func


@deprecated
def test_function():
  """Docstring for test_function.

  THIS FUNCTION IS DEPRECATED and will be removed after some time.
  """
  pass


class TestClass(object):
  """Docstring for TestClass itself."""

  class ChildClass(object):
    """Docstring for a child class."""

    class GrandChildClass(object):
      """Docstring for a child of a child class."""
      pass


class DummyVisitor(object):

  def __init__(self, index, duplicate_of):
    self.index = index
    self.duplicate_of = duplicate_of


class GenerateTest(absltest.TestCase):
  _BASE_DIR = tempfile.mkdtemp()

  def setUp(self):
    super(GenerateTest, self).setUp()
    self.workdir = os.path.join(self._BASE_DIR, self.id())
    os.makedirs(self.workdir)

  def get_test_objects(self):
    # These are all mutable objects, so rebuild them for each test.
    # Don't cache the objects.
    module = sys.modules[__name__]

    index = {
        'tf':
            sys,  # Can be any module, this test doesn't care about content.
        'tf.TestModule':
            module,
        'tf.test_function':
            test_function,
        'tf.TestModule.test_function':
            test_function,
        'tf.TestModule.TestClass':
            TestClass,
        'tf.TestModule.TestClass.ChildClass':
            TestClass.ChildClass,
        'tf.TestModule.TestClass.ChildClass.GrandChildClass':
            TestClass.ChildClass.GrandChildClass,
    }

    tree = {
        'tf': ['TestModule', 'test_function'],
        'tf.TestModule': ['test_function', 'TestClass'],
        'tf.TestModule.TestClass': ['ChildClass'],
        'tf.TestModule.TestClass.ChildClass': ['GrandChildClass'],
        'tf.TestModule.TestClass.ChildClass.GrandChildClass': []
    }

    duplicate_of = {'tf.test_function': 'tf.TestModule.test_function'}

    duplicates = {
        'tf.TestModule.test_function': [
            'tf.test_function', 'tf.TestModule.test_function'
        ]
    }

    base_dir = os.path.dirname(__file__)

    visitor = DummyVisitor(index, duplicate_of)

    reference_resolver = parser.ReferenceResolver.from_visitor(
        visitor=visitor, py_module_names=['tf'], link_prefix='api_docs/python')

    parser_config = config.ParserConfig(
        reference_resolver=reference_resolver,
        duplicates=duplicates,
        duplicate_of=duplicate_of,
        tree=tree,
        index=index,
        reverse_index={},
        base_dir=base_dir,
        code_url_prefix='/')

    return reference_resolver, parser_config

  def test_write(self):
    _, parser_config = self.get_test_objects()

    output_dir = pathlib.Path(self.workdir)

    generate_lib.write_docs(
        output_dir=output_dir,
        parser_config=parser_config,
        root_module_name='tf',
        yaml_toc=True)

    # Check redirects
    redirects_file = output_dir / 'tf/_redirects.yaml'
    self.assertTrue(redirects_file.exists())
    redirects = yaml.safe_load(redirects_file.read_text())
    self.assertEqual(
        redirects, {
            'redirects': [{
                'from': '/api_docs/python/tf/test_function',
                'to': '/api_docs/python/tf/TestModule/test_function'
            }, {
                'from': '/api_docs/python/tf_overview',
                'to': '/api_docs/python/tf'
            }]
        })

    toc_file = output_dir / 'tf/_toc.yaml'
    self.assertTrue(toc_file.exists())
    toc_list = yaml.safe_load(toc_file.read_text())['toc']

    # Number of sections in the toc should be 2.
    self.assertLen([item for item in toc_list if 'section' in item], 2)

    # The last path in the TOC must be the ground truth below.
    # This will check if the symbols are being sorted in case-insensitive
    # alphabetical order too, spanning across submodules and children.
    test_function_toc = toc_list[1]['section'][-1]
    self.assertEqual(test_function_toc['path'],
                     '/api_docs/python/tf/TestModule/test_function')
    self.assertEqual(test_function_toc['status'], 'deprecated')

    # Make sure that the right files are written to disk.
    self.assertTrue((output_dir / 'tf/all_symbols.md').exists())
    self.assertTrue((output_dir / 'tf.md').exists())
    self.assertTrue((output_dir / 'tf/TestModule.md').exists())
    self.assertFalse((output_dir / 'tf/test_function.md').exists())
    self.assertTrue((output_dir / 'tf/TestModule/TestClass.md').exists())
    self.assertTrue(
        (output_dir / 'tf/TestModule/TestClass/ChildClass.md').exists())
    self.assertTrue(
        (output_dir /
         'tf/TestModule/TestClass/ChildClass/GrandChildClass.md').exists())
    # Make sure that duplicates are not written
    self.assertTrue((output_dir / 'tf/TestModule/test_function.md').exists())

  def _get_test_page_info(self):
    page_info = parser.FunctionPageInfo(
        full_name='abc', py_object=test_function)
    docstring_info = parser._DocstringInfo(
        brief='hello `tensorflow`',
        docstring_parts=['line1', 'line2'],
        compatibility={})
    page_info.set_doc(docstring_info)
    return page_info

  def test_get_headers_global_hints(self):
    page_info = self._get_test_page_info()
    result = '\n'.join(generate_lib._get_headers(page_info, search_hints=True))

    expected = textwrap.dedent("""\
      description: hello tensorflow

      <div itemscope itemtype="http://developers.google.com/ReferenceObject">
      <meta itemprop="name" content="abc" />
      <meta itemprop="path" content="Stable" />
      </div>
      """)

    self.assertEqual(expected, result)

  def test_get_headers_global_no_hints(self):
    page_info = self._get_test_page_info()
    result = '\n'.join(generate_lib._get_headers(page_info, search_hints=False))

    expected = textwrap.dedent("""\
      description: hello tensorflow
      robots: noindex
      """)

    self.assertEqual(expected, result)

  def test_get_headers_local_no_hints(self):
    page_info = self._get_test_page_info()

    @doc_controls.hide_from_search
    def py_object():
      pass

    page_info.py_object = py_object

    result = '\n'.join(generate_lib._get_headers(page_info, search_hints=True))

    expected = textwrap.dedent("""\
      description: hello tensorflow
      robots: noindex
      """)

    self.assertEqual(expected, result)


if __name__ == '__main__':
  absltest.main()
