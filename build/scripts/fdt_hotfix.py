# Copyright 2023 SANCTUARY Systems GmbH
# Copyright 2017 Martin Olejar
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

# This file is a patch for pyFDT by Martin Olejar (molejar).
# In the upstream version, single-line empty node definitions break parsing.

from fdt import items, misc, FDT
import os

class FDT_HOTFIX(FDT):
    def parse_dts(text: str, root_dir: str = '') -> FDT:
        """
        Parse DTS text file and create FDT Object

        :param text:
        :param root_dir: 
        """
        ver = misc.get_version_info(text)
        text = misc.strip_comments(text)
        dts_lines = misc.split_to_lines(text)
        fdt_obj = FDT()
        if 'version' in ver:
            fdt_obj.header.version = ver['version']
        if 'last_comp_version' in ver:
            fdt_obj.header.last_comp_version = ver['last_comp_version']
        if 'boot_cpuid_phys' in ver:
            fdt_obj.header.boot_cpuid_phys = ver['boot_cpuid_phys']
        # parse entries
        fdt_obj.entries = []
        for line in dts_lines:
            if line.endswith('{'):
                break
            if line.startswith('/memreserve/'):
                line = line.strip(';')
                line = line.split()
                if len(line) != 3 :
                    raise Exception()
                fdt_obj.entries.append({'address': int(line[1], 0), 'size': int(line[2], 0)})
        # parse nodes
        curnode = None
        fdt_obj.root = None
        node_needs_fix = False

        for line in dts_lines:
            if line.endswith('{'):
                # start node
                if ':' in line:  #indicates the present of a label
                    label, rest = line.split(':')
                    node_name = rest.split()[0]
                    new_node = items.Node(node_name)
                    new_node.set_label(label)
                else:
                    node_name = line.split()[0]
                    new_node = items.Node(node_name)
                if fdt_obj.root is None:
                    fdt_obj.root = new_node
                if curnode is not None:
                    curnode.append(new_node)
                else:
                    node_needs_fix = True
                curnode = new_node

            elif line.endswith('}'):
                if curnode is not None:
                    # HOTFIX for empty nodes
                    if node_needs_fix:
                        node_needs_fix = False

                        line_name = line.split('{')[0].strip()

                        # add empty node
                        if len(line_name) > 1:
                            curnode.append(items.Node(line_name))    
                            continue

                    if curnode.get_property('phandle') is None:
                        if hasattr(curnode, 'label') and curnode.label is not None:
                            handle = fdt_obj.add_label(curnode.label)
                            curnode.set_property('phandle', handle)
                    curnode = curnode.parent
            else:
                # properties
                if line.find('=') == -1:
                    prop_name = line
                    prop_obj = items.Property(prop_name)
                else:
                    line = line.split('=', maxsplit=1)
                    prop_name = line[0].rstrip(' ')
                    prop_value = line[1].lstrip(' ')
                    if prop_value.startswith('<'):
                        prop_obj = items.PropWords(prop_name)
                        prop_value = prop_value.replace('<', '').replace('>', '')
                        # ['interrupts ' = ' <0 5 4>, <0 6 4>']
                        # just change ',' to ' ' -- to concatenate the values into single array
                        if ',' in prop_value:
                            prop_value = prop_value.replace(',', ' ')
                        
                        # keep the orginal references for phandles as a phantom
                        # property
                        if "&" in prop_value:
                            phantom_obj = items.PropStrings(prop_name+'_with_references')
                            phantom_obj.append(line[1].lstrip(' '))
                            if curnode is not None:
                                curnode.append(phantom_obj)
                        for prop in prop_value.split():
                            if prop.startswith('0x'):
                                prop_obj.append(int(prop, 16))
                            elif prop.startswith('0b'):
                                prop_obj.append(int(prop, 2))
                            elif prop.startswith('0'):
                                prop_obj.append(int(prop, 8))
                            elif prop.startswith('&'):
                                prop_obj.append(fdt_obj.add_label(prop[1:]))
                            else:
                                prop_obj.append(int(prop))
                    elif prop_value.startswith('['):
                        prop_obj = items.PropBytes(prop_name)
                        prop_value = prop_value.replace('[', '').replace(']', '')
                        for prop in prop_value.split():
                            prop_obj.append(int(prop, 16))
                    elif prop_value.startswith('/incbin/'):
                        prop_value = prop_value.replace('/incbin/("', '').replace('")', '')
                        prop_value = prop_value.split(',')
                        file_path  = os.path.join(root_dir, prop_value[0].strip())
                        file_offset = int(prop_value.strip(), 0) if len(prop_value) > 1 else 0
                        file_size = int(prop_value.strip(), 0) if len(prop_value) > 2 else 0
                        if file_path is None or not os.path.exists(file_path):
                            raise Exception("File path doesn't exist: {}".format(file_path))
                        with open(file_path, "rb") as f:
                            f.seek(file_offset)
                            prop_data = f.read(file_size) if file_size > 0 else f.read()
                        prop_obj = items.PropIncBin(prop_name, prop_data, os.path.split(file_path)[1])
                    elif prop_value.startswith('/plugin/'):
                        raise NotImplementedError("Not implemented property value: /plugin/")
                    elif prop_value.startswith('/bits/'):
                        raise NotImplementedError("Not implemented property value: /bits/")
                    else:
                        prop_obj = items.PropStrings(prop_name)
                        for prop in prop_value.split('",'):
                            prop = prop.replace('"', "")
                            prop = prop.strip()
                            if len(prop) > 0:
                                prop_obj.append(prop)
                if curnode is not None:
                    curnode.append(prop_obj)

        return fdt_obj
