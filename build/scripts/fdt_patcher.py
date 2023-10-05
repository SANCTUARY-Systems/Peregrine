"""
This module implements FDT patching functionalities that are used at build
time to derive VM-specific device trees according to user confiuration.

These features work best if you use our fork of `dtc` to generate marker
information alongsite the DTB files. The marker data helps identify which node
properties are in fact phandle references and ensures that nodes that depend on
a deleted device do not get included in the output DTB.

Although part of these features are made available through the executable script
interface, you should mainly use this as a module in your own script.

For debugging purposes, add this line anywhere in the module:
    code.interact(local=dict(globals(), **locals()))
"""

from fdt_hotfix import FDT_HOTFIX
import fdt
import argparse
import code


################################################################################
########################## INTERNAL UTILITY FUNCTIONS ##########################
################################################################################

def _is_in_whitelist(node_name, whitelist):
    """ Checks if node is part of a whitelisted device (or ancestors)

    Parameters
    ----------
    node_name : [str] Absolute node path
    whitelist : [list(str)] Device whitelist (also absolute paths)

    Return
    ------
    True if device is part of the list; False otherwise
    """
    return True in [ it.startswith(node_name) for it in whitelist ]


def _has_ancestor(node_name, prunelist):
    """ Checks if node is descendant of another in prunelist

    Parameters
    ----------
    node_name : [str] Absolute node path
    prunelist : [list(str)] Device prunelist (also absolute paths)

    Return
    ------
    True if device has ancestor present; False otherwise
    """
    return True in [ node_name.startswith(it) and node_name != it \
                     for it in prunelist ]

################################################################################
########################### FDT {WHITE,BLACK}LISTING ###########################
################################################################################

def get_nodelist(fdt_data, minimal=False):
    """ Returns a list of all absolute node paths in the DT

    Parameters
    ----------
    fdt_data : [fdt.FDT] Target device tree
    minimal  : [bool] Select only leaf devices, not intermediary nodes
               (default: False)

    Returns
    -------
    List of absolute node path strings

    Details
    -------
    Use `minimal=True` to get a device whitelist template. After that, start
    removing devices according to your preference. Note that the resulting
    devices should go in the "device_whitelist" property of VMs/*.json for
    build-time pruning.
    """
    return [ it[0] for it in fdt_data.walk('', False) \
                   if not minimal or len(it[1]) == 0 ]


def prune_node(node_path, fdt_data):
    """ Removes node from FDT

    Parameters
    ----------
    node_path: [str] Node's absolute path in FDT
    fdt_data  : [fdt.FDT] Target device tree

    Details
    -------
    Aside from removing node in question, this function also affects any
    related nodes, such as "/aliases".
    """

    # attempt to get node using provided FDT path
    try:
        node = fdt_data.get_node(node_path)
    except:
        print('WAR: unable to get node "%s"' % node_path)
        return

    # check if node alias needs deleting
    try:
        aliases   = fdt_data.get_node('/aliases')
        to_delete = [ it for it in aliases.props if it.data[0] == node_path]

        # potentially corrupted FDT; should have one alias per device
        if len(to_delete) > 1:
            print('WAR: multiple aliases for "%s" node' % node_path)

        for it in to_delete:
            aliases.remove_property(it.name)
    except:
        pass

    # TODO: add phandle check based on optional marker information

    # delete node
    sep_idx   = node_path.rfind('/')

    if sep_idx != -1:
        fdt_data.remove_node(node_path[sep_idx + 1 :], node_path[:sep_idx])
    else:
        print('ERR: invalid node path "%s"' % node_path)


def apply_blacklist(fdt_data, blacklist):
    """ Removes nodes that are part of the blacklist

    Parameters
    ----------
    fdt_data  : [fdt.FDT] Target device tree
    blacklist : [list(str)] List of absolute node paths; children are deleted
                as well
    """

    for it in blacklist:
        prune_node(it, fdt_data)


def apply_whitelist(fdt_data, whitelist):
    """ Removes nodes that are not part of the whitelist

    Parameters
    ----------
    fdt_data  : [fdt.FDT] Target device tree
    whitelist : [list(str)] List of absolute node paths; every node on each
                path is included
    """

    # get a full node list from the FDT data before starting to cut things
    nodelist = get_nodelist(fdt_data, False)

    # calculate blacklist, then minimize it to set of oldest common ancestors
    blacklist = [ it for it in nodelist if not _is_in_whitelist(it, whitelist) ]
    blacklist = [ it for it in blacklist if not _has_ancestor(it, blacklist) ]

    apply_blacklist(fdt_data, blacklist)

################################################################################
################################ FDT TOUCH-UPS #################################
################################################################################

def set_chosen(fdt_data, bootargs=None, stdout=None, rd_start=None, rd_end=None):
    """ Overrides (and optionally creates) the "chosen" node

    Parameters
    ----------
    fdt_data : [fdt.FDT] Target device tree
    bootargs : [str] Kernel cmdline arguments (default: None)
    stdout   : [str | None] Kernel standard output (default: None)
    rd_start : [int | None] InitRamdisk start address (default: None)
    rd_end   : [int | None] InitRamdisk end address (default: None)

    Returns
    -------
    True if everything went well; False otherwise

    Details
    -------
    The "stdout-path" property is optional since we can specify the tty in
    "bootargs. Same applies for "linux,initrd-{start,end}" because we
    can just pass it "root=/dev/ram0" for example.

    If we are not booting the kernel from Peregrine, note that U-Boot will
    override the "bootargs" property with its environment variable bearing
    the same name, after you `bootm` into the FIT image.

    If any argument holds the default `None` value, this function will try
    to extract the value from the previous `chosen` node and reuse it. If no
    such property existed in the now-deleted `chosen` node, none will be
    added to the new version.
    """

    # extract relevant properties from previous "/chosen" node if none were
    # specified; then delete the "/chosen" node in preparation for new one
    try:
        chosen = fdt_data.get_node('/chosen')

        if bootargs is None:
            prop = chosen.get_property('bootargs')
            if prop is not None:
                bootargs = prop.data[0]

        if stdout is None:
            prop = chosen.get_property('stdout-path')
            if prop is not None:
                stdout = prop.data[0]

        if rd_start is None:
            prop = chosen.get_property('linux,initrd-start')
            if prop is not None:
                rd_start = prop.data[0]

        if rd_end is None:
            prop = chosen.get_property('linux,initrd-end')
            if prop is not None:
                rd_end = prop.data[0]

        fdt_data.remove_node('chosen', '/')
    except:
        pass

    # create a new "/chosen" node; start adding new or recovered properties
    chosen = fdt.Node('chosen')

    if bootargs is not None:
        chosen.append(fdt.PropStrings('bootargs', bootargs))

    if stdout is not None:
        chosen.append(fdt.PropStrings('stdout-path', stdout))

    if rd_start is not None and rd_end is not None:
        chosen.append(fdt.PropWords('linux,initrd-start', rd_start))
        chosen.append(fdt.PropWords('linux,initrd-end',   rd_end))

    # attach new node to root of DT
    fdt_data.add_item(chosen, '/')

    return True


def set_memory(fdt_data, mem_sz, kernel_addr,
               fdt_addr=(2**64 - 1), ramdisk_addr=(2**64 - 1)):
    """ Overrides (and optionally creates) the "memory" node

    Parameters
    ----------
    fdt_data     : [fdt.FDT] Target device tree
    mem_sz       : [int] Total memory size
    kernel_addr  : [int] Kernel base address
    fdt_addr     : [int] FDT base address (default: U64_MAX)
    ramdisk_addr : [int] Ramdisk base address (default: U64_MAX)

    Returns
    -------
    True if everything went well; False otherwise

    Details
    -------
    The memory range will start at the minimum address where either the kernel,
    the fdt or the ramdisk are mapped in the IPA. In case an FDT or ramdisk
    starting address are not provided, the maxium 32-bit value will be assumed.
    We consider the kernel to be a mandatory component of the VM so its address
    is required.
    """

    # calcualte accessible memory starting address
    mem_start = min(kernel_addr, fdt_addr, ramdisk_addr)

    # try finding and deleting any existing "memory@..." node(s)
    mem_nodes = [ it for it in fdt_data.search('', itype=fdt.ItemType.NODE)
                  if it.name.startswith('memory@') ]
    for it in mem_nodes:
        fdt_data.remove_node(it.name, '/')

    # create a new "/memory@..." node
    mask = 0xffffffff

    memory = fdt.Node('memory@%x' % mem_start)
    memory.append(fdt.PropStrings('device_type', 'memory'))
    memory.append(fdt.PropWords('reg',
                                (mem_start >> 32) & mask, mem_start & mask,
                                (mem_sz    >> 32) & mask, mem_sz    & mask))

    # attach new node to root of DT
    fdt_data.add_item(memory, '/')

    return True


def set_cpus(fdt_data, cpu_whitelist):
    """ Removes unwanted CPU nodes from "/cpus"

    Parameters
    ----------
    fdt_data      : [fdt.FDT] Target device tree
    cpu_whitelist : [list(int)] "reg" values of wanted CPU nodes

    Returns
    -------
    True if everything went well; False otherwise

    Details
    -------
    The "/cpus" node may have additional children such as "idle-states",
    "l2-cache0", etc. This function will never remove these nodes, but
    only "cpu@...".

    Depending on the "#address-cells" property of "/cpus", the "reg" property of
    "cpu@..." nodes can have an arbitrary number of 32-bit values (usually 1-2).
    Since MPIDR-style affinity is expressed within 32 bits, only the least
    significant dword of "reg" is evaluated.

    NOTE: Depending on the MT bit of the MPIDR register, Aff0 (i.e.: MPIDR[7:0])
          can represent either cores or physical threads. So CPU3 can have a
          "reg" value of 0x300 on some systems or 0x3 on other systems. Best
          consult the device tree when composing the CPU whitelist.
    """
    try:
        # obtain list of "cpu@..." nodes whose affinity (i.e.: "reg" property)
        # is not included in our whitelist; then, convert it to list of absolute
        # paths within the FDT
        cpus          = fdt_data.get_node('/cpus')
        cpu_blacklist = [ it for it in cpus.nodes
                          if  it.name.startswith('cpu@')
                          and it.get_property('reg').data[-1]
                              not in cpu_whitelist ]
        cpu_blacklist = [ '%s/%s' % (it.path, it.name) for it in cpu_blacklist ]

        # delete "cpu@..." nodes that were not found in whitelist
        apply_blacklist(fdt_data, cpu_blacklist)
    except:
        print('ERR: unable to filter "cpu@..." nodes')
        return False

    return True


def trim_excess_cpus(fdt_data, num_cpus):
    """ Retains only the first `num_cpus` nodes in "/cpus"

    Parameters
    ----------
    fdt_data : [fdt.FDT] Target device tree
    num_cpus : [int] Number of CPUs to retain

    Returns
    -------
    True if everything went well; False otherwise

    Details
    -------
    Apparently Linux throws a hissy fit if the secondary VM's "cpu@..." nodes
    are mapped to the physical CPU IDs and not the vCPU IDs. Meaning that even
    if we allocate CPUs N-1, N-2, ... to a secondary VM, them not being
    represented by "cpu@0", "cpu@1", ... in the FDT causes the VM to hang early
    on.
    """
    try:
        # get list of CPUs; FDT ordering preserved
        cpus     = fdt_data.get_node('/cpus')
        cpu_list = [ it for it in cpus.nodes if it.name.startswith('cpu@') ]

        cpu_blacklist = [ '%s/%s' % (it.path, it.name)
                          for it in cpu_list[num_cpus:] ]

        # delete excess CPUs
        apply_blacklist(fdt_data, cpu_blacklist)
    except:
        print('ERR: unable to identify & trim excess "cpu@..." nodes')
        return False

    return True

################################################################################
############################## FDT I/O OPERATIONS ##############################
################################################################################

def parse_fdt(fdt_name):
    """ Loads FDT object from file

    Parameters
    ----------
    fdt_name : [str] Input file path

    Returns
    -------
    fdt.FDT object on success
    None           on failure

    Details
    -------
    Parsing method depends on file extension.
    Has support for both DTB and DTS. Suggest sticking with DTB for now.
    """
    if fdt_name.endswith('.dtb'):
        with open(fdt_name, 'rb') as f:
            fdt_data = fdt.parse_dtb(f.read())
    elif fdt_name.endswith('.dts'):
        with open(fdt_name, 'rt') as f:
            fdt_data = FDT_HOTFIX.parse_dts(f.read())
    else:
        print('ERR: unknown FDT file extension for "%s"' % fdt_name)
        fdt_data = None
    
    return fdt_data

def store_fdt(fdt_name, fdt_data):
    """ Stores FDT object to file

    Parameters
    ----------
    fdt_name : [str] Output file path (can be - for stdout)
    fdt_data : [fdt.FDT] Target device tree

    Returns
    -------
    True if everything went well; False otherwise

    Details
    -------
    The FDT can be stored either as DTS or DTB depending on the file extension.
    """

    if fdt_name == '-':
        print(fdt_data.to_dts())
    elif fdt_name.endswith('.dtb'):
        with open(fdt_name, 'wb') as f:
            f.write(fdt_data.to_dtb())
    elif fdt_name.endswith('.dts'):
        with open(fdt_name, 'wt') as f:
            f.write(fdt_data.to_dts())
    else:
        print('ERR: unknwown FDT file extension for "%s"' % fdt_name)
        return False

    return True

################################################################################
################################ CLI INTERFACE #################################
################################################################################

def CLI_dump_whitelist(args):
    fdt_data = parse_fdt(args.fdt_in)
    if fdt_data is None:
        exit(-1)

    nodelist = get_nodelist(fdt_data, True)

    print(4 * ' ' + '"device_whitelist": [')
    for it in nodelist[:-1]:
        print(8 * ' ' + '"%s",' % it)
    print(8 * ' ' + '"%s"' % nodelist[-1])
    print(4 * ' ' + '],')


def CLI_delete_nodes(args):
    fdt_data = parse_fdt(args.fdt_in)
    if fdt_data is None:
        exit(-1)

    for node_name in args.prune_list:
        prune_node(node_name, fdt_data)

    ans = store_fdt(args.fdt_out, fdt_data)
    if ans is False:
        exit(-1)


def CLI_set_memory(args):
    fdt_data = parse_fdt(args.fdt_in)
    if fdt_data is None:
        exit(-1)

    set_memory(fdt_data, args.mem_sz, args.kern_base,
               args.fdt_base, args.rd_base)

    ans = store_fdt(args.fdt_out, fdt_data)
    if ans is False:
        exit(-1)


def main():
    parser = argparse.ArgumentParser(
                        prog='fdt_patcher.py',
                        description='FDT patching features for SANCTUARY')
    subparsers = parser.add_subparsers(title='Subcommands')

    # print whitelist template to be copy pasted to JSON file
    parser_1 = subparsers.add_parser('whitelist',
                                help='print whitelist template for JSON')
    parser_1.add_argument('-i', metavar='FILE', type=str,
                          required = True, dest='fdt_in',
                          help='input DTB or DTS')
    parser_1.set_defaults(func=CLI_dump_whitelist)

    # delete one or more nodes from FDT by path
    parser_2 = subparsers.add_parser('delete-nodes',
                                help='delete one or more nodes from FDT')

    parser_2.add_argument('-i', metavar='FILE', type=str,
                          required=True, dest='fdt_in',
                          help='input DTB or DTS')
    parser_2.add_argument('-o', metavar='FILE', type=str,
                          required=False, dest='fdt_out', default='-',
                          help='output DTB or DTS (default: latter to stdout)')
    parser_2.add_argument('-d', action='append', metavar='<node_path>', type=str,
                          required=False, dest='prune_list', default=[],
                          help='path of deleted node')
    parser_2.set_defaults(func=CLI_delete_nodes)

    # TODO: subcommand for setting "/chosen" node

    # override memory node
    parser_4 = subparsers.add_parser('set-memory',
                                help='override memory node')

    parser_4.add_argument('-i', metavar='FILE', type=str,
                          required=True, dest='fdt_in',
                          help='input DTB or DTS')
    parser_4.add_argument('-o', metavar='FILE', type=str,
                          required=False, dest='fdt_out', default='-',
                          help='output DTB or DTS (default: latter to stdout)')
    parser_4.add_argument('-s', metavar='UINT', type=lambda x: int(x, 0),
                          required=True, dest='mem_sz',
                          help='memory range size [bytes]')
    parser_4.add_argument('-k', metavar='UINT', type=lambda x: int(x, 0),
                          required=True, dest='kern_base',
                          help='kernel base address')
    parser_4.add_argument('-f', metavar='UINT', type=lambda x: int(x, 0),
                          required=False, dest='fdt_base', default=(2**64 - 1),
                          help='FDT base address')
    parser_4.add_argument('-r', metavar='UINT', type=lambda x: int(x, 0),
                          required=False, dest='rd_base', default=(2**64 - 1),
                          help='ramdisk base address')
    parser_4.set_defaults(func=CLI_set_memory)

    # parse arguments and display help if no subcommand was provided
    args = parser.parse_args()
    if 'func' not in args:
        parser.print_help()
        exit(-1)

    # invoke subcommand-specific handler
    args.func(args)


if __name__ == '__main__':
    main()

