#!/bin/python
""" Script for deriving topdown metrics from a Json file produced by Caliper. """

from __future__ import print_function
import sys
import pandas as pd

pd.set_option('display.expand_frame_repr', False)

METRICS = [
    'retiring',
    'bad_speculation',
    'frontend_bound',
    'backend_bound',
    'branch_mispredict',
    'machine_clear',
    'frontend_latency',
    'frontend_bandwidth',
    'memory_bound',
    'core_bound',
    'mem_bound',
    'l1_bound',
    'l2_bound',
    'l3_bound',
    'uncore_bound',
]

IVB_SLOTS = 4
IVB_L1LAT = 7
IVB_ARCH = {
    'clocks'                : 'libpfm.counter.CPU_CLK_UNHALTED.THREAD_P',
    'retire_slots'          : 'libpfm.counter.UOPS_RETIRED.RETIRE_SLOTS',
    'recovery_cycles'       : 'libpfm.counter.INT_MISC.RECOVERY_CYCLES',
    'uops_any'              : 'libpfm.counter.UOPS_ISSUED.ANY',
    'uops_not_delivered'    : 'libpfm.counter.IDQ_UOPS_NOT_DELIVERED.CORE',
    'branches'              : 'libpfm.counter.BR_MISP_RETIRED.ALL_BRANCHES',
    'machine_clears'        : 'libpfm.counter.MACHINE_CLEARS.COUNT',
    'idle_cycles'           : 'libpfm.counter.CYCLE_ACTIVITY.CYCLES_NO_EXECUTE',
    'thread_c1'             : 'libpfm.counter.UOPS_EXECUTED.THREAD:c=1',
    'thread_c2'             : 'libpfm.counter.UOPS_EXECUTED.THREAD:c=2',
    'l3_hit'                : 'libpfm.counter.MEM_LOAD_UOPS_RETIRED.L3_HIT',
    'l3_miss'               : 'libpfm.counter.MEM_LOAD_UOPS_RETIRED.L3_MISS',
    'mem_stalls'            : 'libpfm.counter.CYCLE_ACTIVITY.STALLS_LDM_PENDING',
    'l1_stalls'             : 'libpfm.counter.CYCLE_ACTIVITY.STALLS_L1D_PENDING',
    'l2_stalls'             : 'libpfm.counter.CYCLE_ACTIVITY.STALLS_L2_PENDING',
}

BDW_SLOTS = 4
BDW_L1LAT = 7
BDW_ARCH = {
    'clocks'                : 'libpfm.counter.CPU_CLK_THREAD_UNHALTED',
    'retire_slots'          : 'libpfm.counter.UOPS_RETIRED.RETIRE_SLOTS',
    'recovery_cycles'       : 'libpfm.counter.INT_MISC.RECOVERY_CYCLES',
    'uops_any'              : 'libpfm.counter.UOPS_ISSUED.ANY',
    'uops_not_delivered'    : 'libpfm.counter.IDQ_UOPS_NOT_DELIVERED.CORE',
    'branches'              : 'libpfm.counter.BR_MISP_RETIRED:ALL_BRANCHES',
    'machine_clears'        : 'libpfm.counter.MACHINE_CLEARS.COUNT',
    'idle_cycles'           : 'libpfm.counter.CYCLE_ACTIVITY.CYCLES_NO_EXECUTE',
    'thread_c1'             : 'libpfm.counter.UOPS_EXECUTED.THREAD:c=1',
    'thread_c2'             : 'libpfm.counter.UOPS_EXECUTED.THREAD:c=2',
    'l3_hit'                : 'libpfm.counter.MEM_LOAD_UOPS_RETIRED.L3_HIT',
    'l3_miss'               : 'libpfm.counter.MEM_LOAD_UOPS_RETIRED.L3_MISS',
    'mem_stalls'            : 'libpfm.counter.CYCLE_ACTIVITY.STALLS_LDM_PENDING',
    'l1_stalls'             : 'libpfm.counter.CYCLE_ACTIVITY.STALLS_L1D_PENDING',
    'l2_stalls'             : 'libpfm.counter.CYCLE_ACTIVITY.STALLS_L2_PENDING',
}


def eprint(*args, **kwargs):
    """ Print to stderr """

    print(*args, file=sys.stderr, **kwargs)


def derive_topdown(dfm, arch_name):
    """ Perform topdown metric calculations for ivybridge architecture """

    if arch_name == 'ivybridge':
        arch = IVB_ARCH
        slots = IVB_SLOTS
        l1lat = IVB_L1LAT
    elif arch_name == 'broadwell':
        arch = BDW_ARCH
        slots = BDW_SLOTS
        l1lat = BDW_L1LAT
    else:
        eprint("Error, unsupported architecture " + arch_name)
        sys.exit(1)

    dfm['TEMPORARY_slots'] = slots*dfm[arch['clocks']]

    # Level 1 - Not Stalled
    dfm['retiring'] = (dfm[arch['retire_slots']]
                       / dfm['TEMPORARY_slots'])
    dfm['bad_speculation'] = ((dfm[arch['uops_any']]
                               - dfm[arch['retire_slots']]
                               + slots*dfm[arch['recovery_cycles']])
                              / dfm['TEMPORARY_slots'])

    # Level 1 - Stalled
    dfm['frontend_bound'] = (dfm[arch['uops_not_delivered']]
                             / dfm['TEMPORARY_slots'])
    dfm['backend_bound'] = (1 - (dfm['frontend_bound']
                                 + dfm['bad_speculation']
                                 + dfm['retiring']))

    # Level 2 - Retiring
    # TODO: implement if possible

    # Level 2 - Bad speculation
    dfm['branch_mispredict'] = (dfm[arch['branches']]
                                / (dfm[arch['branches']]
                                   + dfm[arch['machine_clears']]))
    dfm['machine_clear'] = (1 - dfm['branch_mispredict'])  # FIXME: is this correct?

    # Level 2 - Frontend Bound
    dfm['frontend_latency'] = (dfm[arch['uops_not_delivered']].clip(lower=slots)
                               / dfm[arch['clocks']])
    dfm['frontend_bandwidth'] = (1 - dfm['frontend_latency'])  # FIXME: is this correct?

    # Level 2 - Backend Bound
    dfm['memory_bound'] = (dfm[arch['mem_stalls']]
                           / dfm[arch['clocks']])
    dfm['TEMPORARY_be_bound_at_exe'] = ((dfm[arch['idle_cycles']]
                                         + dfm[arch['thread_c1']]
                                         - dfm[arch['thread_c2']])
                                        / dfm[arch['clocks']])
    dfm['core_bound'] = (dfm['TEMPORARY_be_bound_at_exe']
                         - dfm['memory_bound'])

    # Level 3 - Memory bound
    dfm['TEMPORARY_l3_hit_fraction'] = (dfm[arch['l3_hit']] /
                                        (dfm[arch['l3_hit']]
                                         + l1lat*dfm[arch['l3_miss']]))
    dfm['TEMPORARY_l3_miss_fraction'] = (l1lat*dfm[arch['l3_miss']]
                                         / (dfm[arch['l3_hit']]
                                            + l1lat*dfm[arch['l3_miss']]))
    dfm['mem_bound'] = (dfm[arch['l2_stalls']]
                        * dfm['TEMPORARY_l3_miss_fraction']
                        / dfm[arch['clocks']])
    dfm['l1_bound'] = ((dfm[arch['mem_stalls']]
                        - dfm[arch['l1_stalls']])
                       / dfm[arch['clocks']])
    dfm['l2_bound'] = ((dfm[arch['l1_stalls']]
                        - dfm[arch['l2_stalls']])
                       / dfm[arch['clocks']])
    dfm['l3_bound'] = (dfm[arch['l2_stalls']]
                       * dfm['TEMPORARY_l3_hit_fraction']
                       / dfm[arch['clocks']])
    dfm['uncore_bound'] = (dfm[arch['l2_stalls']]
                           / dfm[arch['clocks']])

    for column in dfm.columns:
        if 'TEMPORARY' in column:
            del dfm[column]
        elif 'libpfm.counter' in column:
            del dfm[column]

    return dfm


def max_column(row, columns):
    """ Returns the column name for the column with the largest value in row """

    return max([(column, row[column]) for column in columns],
               key=lambda t: t[1])[0]


def percentage_string(val):
    """ Returns a percentage-formatted string for a value, e.g. 0.9234 becomes 92.34% """

    return '{:,.2%}'.format(val)


def determine_boundedness(row):
    """ Determine the boundedness of a single row with topdown metrics """

    boundedness = []

    level_1 = max_column(row, ['retiring',
                               'bad_speculation',
                               'frontend_bound',
                               'backend_bound'])
    if str(row[level_1]) != 'nan' and str(row[level_1]) != 'inf':
        boundedness.append(level_1 + ' ' + percentage_string(row[level_1]))

    if level_1 == 'bad_speculation':
        level_2 = max_column(row, ['branch_mispredict',
                                   'machine_clear'])
        boundedness.append(level_2 + ' ' + percentage_string(row[level_2]))
    elif level_1 == 'frontend_bound':
        level_2 = max_column(row, ['frontend_latency',
                                   'frontend_bandwidth'])
        boundedness.append(level_2 + ' ' + percentage_string(row[level_2]))
    elif level_1 == 'backend_bound':
        level_2 = max_column(row, ['core_bound',
                                   'memory_bound'])
        boundedness.append(level_2 + ' ' + percentage_string(row[level_2]))
        if level_2 == 'memory_bound':
            level_3 = max_column(row, ['l1_bound',
                                       'l2_bound',
                                       'l3_bound',
                                       'mem_bound',
                                       'uncore_bound'])
            boundedness.append(level_3 + ' ' + percentage_string(row[level_3]))

    if len(boundedness) == 0:
        boundedness.append('undetermined')

    return boundedness


def analyze_topdown_metrics(dfm):
    """ Analyze topdown metrics to determine boundedness of different Caliper regions """

    dfm['boundedness'] = dfm.apply(determine_boundedness, axis=1)

    for metric in METRICS:
        del dfm[metric]

    return [dict([col for col in row.items() if str(col[1]) != 'nan'])
            for row in dfm.to_dict('index').values()]


def main():
    """ Print all Caliper entries with their derived metrics """

    if len(sys.argv) != 3:
        eprint("Usage: " + sys.argv[0] + " <json file> <arch, e.g. ivybridge>")

    dfm = pd.read_json(sys.argv[1])

    dfm = derive_topdown(dfm, sys.argv[2])

    analysis = analyze_topdown_metrics(dfm)

    for row in analysis:
        print(row)


if __name__ == "__main__":
    main()
