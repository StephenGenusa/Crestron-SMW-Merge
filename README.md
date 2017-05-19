# SMW Merge from Google Code #


#### License ####
Copyright Ian Epperson.  Parts based on a file called mymerge.py written by Marcos Chaves.

This software may be used and distributed according to the terms
of the GNU General Public License, incorporated herein by reference.


#### Background ####
Although Crestron's SIMPL Windows files are clear text, they are not able to be merged by traditional methods due to the internal cross references within those files. 

#### What does it do? ####
This utility unwraps the internal cross references and performs a proper three-way merge. It will merge symbols, signals and can even merge inputs and outputs within a symbol. 

#### What does that let me do? ####
A proper three-way merge allows a group of developers to collaborate on a project using an SCM system like Subversion. Multiple developers can make changes in the same file and this utility will merge those changes as necessary. 

#### What doesn't it do? ####
The current version does not have the conflict handler functioning. If it comes across a conflict (that is, you and another developer both make changes to the same symbol or add a subsystem in the same location) your change will be removed. Thankfully, this shouldn't happen often at all, but will be handled in a future version. There is no way to represent hardware change conflicts. For instance, if you and another developer add two different Cresnet devices at address 03, your changes will be lost. Again, this shouldn't happen often. 

#### Current state ####
Alpha Release! This is an Alpha release that has only been lightly tested. DO NOT RELY ON THIS YET - Much more testing must be done.
