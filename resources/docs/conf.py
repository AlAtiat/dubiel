# Configuration file for the Sphinx documentation builder.
# See https://www.sphinx-doc.org/en/master/usage/configuration.html

project = 'Dubiel'
author = 'Aun Al Atiat'
copyright = '2026, AlAtiat'

version = '0.0.1'
release = '0.0.1'

extensions = [
    'sphinx.ext.mathjax',
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

epub_title = 'Dubiel'
epub_author = 'Aun Al Atiat'
epub_publisher = 'Aun Al Atiat'
epub_copyright = copyright

numfig = True
