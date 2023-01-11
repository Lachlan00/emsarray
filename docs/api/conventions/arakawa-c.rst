==============================
emsarray.conventions.arakawa_c
==============================

.. automodule:: emsarray.conventions.arakawa_c

.. autoclass:: ArakawaC
   :members: face, left, back, node

Indexing
========

Arakawa C grid datasets have four :ref:`grids <grids>`:
*face*, *left*, *back*, and *node*.
:class:`ArakawaCGridKind` represents this.
Each grid is :ref:`indexed <indexing>` by a grid kind and two integers *i* and *j*.
The convention native index type is :data:`ArakawaCIndex`.

.. autoclass:: ArakawaCGridKind
   :members:
   :undoc-members:

.. autodata:: ArakawaCIndex

Topology
========

.. autoclass:: ArakawaCGridTopology
   :members:

Functions
=========

.. autofunction:: c_mask_from_centres
