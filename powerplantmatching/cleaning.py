# -*- coding: utf-8 -*-
# Copyright 2016-2018 Fabian Hofmann (FIAS), Jonas Hoersch (KIT, IAI) and
# Fabian Gotzens (FZJ, IEK-STE)

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Functions for vertically cleaning a dataset.
"""
from __future__ import absolute_import, print_function

import logging
import os

import networkx as nx
import numpy as np
import pandas as pd
from deprecation import deprecated

from .core import _data_out, get_config, get_obj_if_Acc
from .duke import duke
from .utils import get_name, set_column_name

logger = logging.getLogger(__name__)


def mode(x):
    """
    Get the most common value of a series.
    """
    return x.mode(dropna=False).at[0]


AGGREGATION_FUNCTIONS = {
    "Name": mode,
    "Fueltype": mode,
    "Technology": mode,
    "Set": mode,
    "Country": mode,
    "Capacity": "sum",
    "lat": "mean",
    "lon": "mean",
    "DateIn": "min",
    "DateRetrofit": "max",  # choose latest Retrofit-Year
    "DateMothball": "min",
    "DateOut": "min",
    "File": mode,
    "projectID": list,
    "EIC": set,
    "Duration": "sum",  # note this is weighted sum
    "Volume_Mm3": "sum",
    "DamHeight_m": "sum",
    "StorageCapacity_MWh": "sum",
    "Efficiency": "mean",  # note this is weighted mean
}


def clean_name(df, config=None):
    """
    Clean the name of a power plant list.

    Cleans the column "Name" of the database by deleting very frequent words
    and nonalphanumerical characters of the column. Returns a  reduced
    dataframe with nonempty Name-column.

    Parameters
    ----------
    df : pandas.Dataframe
        dataframe to be cleaned
    config : dict, default None
        Custom configuration, defaults to
        `powerplantmatching.config.get_config()`.

    """
    df = get_obj_if_Acc(df)

    if config is None:
        config = get_config()

    name = df.Name.astype(str).copy()

    replace = config["clean_name"]["replace"]

    if config["clean_name"]["remove_common_words"]:
        common_words = pd.Series(sum(name.str.split(), [])).value_counts()
        common_words = list(common_words[common_words >= 20].index)
        replace[""] = replace.get("", []) + common_words

    for key, pattern in replace.items():
        if isinstance(pattern, list):
            # if pattern is a list, concat all entries in a case-insensitive regex
            pattern = r"(?i)" + "|".join([rf"\b{p}\b" for p in pattern])
        elif not isinstance(pattern, str):
            raise ValueError(f"Pattern must be string or list, not {type(pattern)}")
        name = name.str.replace(pattern, key, regex=True)

    name = name.str.strip().str.title().str.replace(r" +", " ", regex=True)

    return df.assign(Name=name).sort_values("Name")


@deprecated(deprecated_in="5.0", removed_in="0.6", details="Use `clean_name` instead.")
def clean_powerplantname(df, config=None):
    return clean_name(df, config=config)


def config_target_key(column):
    """
    Convert a column name to the key that is used to specify the target
    values in the config.

    Parameters
    ----------
    column : str
        Name of the column.

    Returns
    -------
    str
        Name of the key used in the config file.
    """
    if column.endswith("y"):
        column = column[:-1] + "ie"
    column = str.lower(column)
    return f"target_{column}s"


def gather_and_replace(df, mapping):
    """
    Search for patterns in multiple columns and return a series of represantativ keys.

    The function will return a series of unique identifyers given by the keys of the
    `mapping` dictionary. The order in the `mapping` dictionary determines which
    represantativ keys are calculated first. Note that these may be overwritten by
    the following mappings.

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame with columns that should be parsed.
    mapping : dict
        Dictionary mapping the represantativ keys to the regex patterns.
    """
    assert isinstance(mapping, dict)
    res = pd.Series(index=df.index, dtype=object)
    for key, pattern in mapping.items():
        if not pattern:
            # if pattern is not given, fall back to case-insensitive key
            pattern = r"(?i)%s" % key
        elif isinstance(pattern, list):
            # if pattern is a list, concat all entries in a case-insensitive regex
            pattern = r"(?i)" + "|".join([rf"\b{p}\b" for p in pattern])
        elif not isinstance(pattern, str):
            raise ValueError(f"Pattern must be string or list, not {type(pattern)}")
        func = lambda ds: ds.str.contains(pattern)
        where = df.astype(str).apply(func).any(1)
        res = res.where(~where, key)
    return res


def gather_specifications(
    df,
    target_columns=["Fueltype", "Technology", "Set"],
    parse_columns=["Name", "Fueltype", "Technology", "Set"],
    config=None,
):
    """
    Parse columns to collect representative keys.


    This function will parse the columns specified in `parse_columns` and collects
    the representative keys for each row in `target_columns`. The parsing is based
    on the config file.

    Parameters
    ----------
    df : pandas.DataFrame
        Power plant dataframe.
    target_columns : list, optional
        Columns where the representative keys will be collected,
        by default ["Fueltype", "Technology", "Set"]
    parse_columns : list, optional
        Columns that should be parsed, by default
        ["Name", "Fueltype", "Technology", "Set"]
    config : dict, default None
        Custom configuration, defaults to
        `powerplantmatching.config.get_config()`.

    Returns
    -------
    pandas.DataFrame
    """

    if config is None:
        config = get_config()

    cols = {}
    for c in target_columns:
        target_key = config_target_key(c)
        keys = config[target_key]
        cols[c] = gather_and_replace(df[parse_columns], keys)

    return df.assign(**cols)


@deprecated(
    deprecated_in="0.5",
    removed_in="0.6",
    details="Use `gather_specifications` instead.",
)
def gather_fueltype_info(
    df, search_col=["Name", "Fueltype", "Technology"], config=None
):
    """
    Parses in a set of columns for distinct fueltype specifications.

    This function uses the mappings (key -> regex pattern) given
    by the `config` under the section `target_technologies`.
    The representative keys are set if any of the columns
    in `search_col` matches the regex pattern.

    Parameter
    ---------
    df : pandas.DataFrame
        DataFrame to be parsed.
    search_col : list, default is ["Name", "Fueltype", "Technology", "Set"]
        Set of columns to be parsed. Must be in `df`.
    config : dict, default None
        Custom configuration, defaults to
        `powerplantmatching.config.get_config()`.
    """
    if config is None:
        config = get_config()

    keys = config["target_fueltypes"]
    fueltype = gather_and_replace(df[search_col], keys)
    return df.assign(Fueltype=fueltype)


@deprecated(
    deprecated_in="0.5",
    removed_in="0.6",
    details="Use `gather_specifications` instead.",
)
def gather_technology_info(
    df, search_col=["Name", "Fueltype", "Technology", "Set"], config=None
):
    """
    Parses in a set of columns for distinct technology specifications.

    This function uses the mappings (key -> regex pattern) given
    by the `config` under the section `target_technologies`.
    The representative keys are set if any of the columns
    in `search_col` matches the regex pattern.

    Parameter
    ---------
    df : pandas.DataFrame
        DataFrame to be parsed.
    search_col : list, default is ["Name", "Fueltype", "Technology", "Set"]
        Set of columns to be parsed. Must be in `df`.
    config : dict, default None
        Custom configuration, defaults to
        `powerplantmatching.config.get_config()`.
    """
    if config is None:
        config = get_config()

    keys = config["target_technologies"]
    technology = gather_and_replace(df[search_col], keys)
    return df.assign(Technology=technology)


@deprecated(
    deprecated_in="0.5",
    removed_in="0.6",
    details="Use `gather_specifications` instead.",
)
def gather_set_info(df, search_col=["Name", "Fueltype", "Technology"], config=None):
    """
    Parses in a set of columns for distinct Set specifications.

    This function uses the mappings (key -> regex pattern) given
    by the `config` under the section `target_sets`.
    The representative keys are set if any of the columns
    in `search_col` matches the regex pattern.

    Parameter
    ---------
    df : pandas.DataFrame
        DataFrame to be parsed.
    search_col : list, default is ["Name", "Fueltype", "Technology", "Set"]
        Set of columns to be parsed. Must be in `df`.
    config : dict, default None
        Custom configuration, defaults to
        `powerplantmatching.config.get_config()`.
    """
    if config is None:
        config = get_config()

    keys = config["target_sets"]
    Set = gather_and_replace(df[search_col], keys)
    return df.assign(Set=Set)


@deprecated(
    deprecated_in="0.5",
    removed_in="0.6",
)
def clean_technology(df, generalize_hydros=False):
    """
    Clean the 'Technology' by condensing down the value into one claim. This
    procedure might reduce the scope of information, however is crucial for
    comparing different data sources.

    Parameter
    ---------
    search_col : list, default is ['Name', 'Fueltype', 'Technology']
        Specify the columns to be parsed
    config : dict, default None
        Add custom specific configuration,
        e.g. powerplantmatching.config.get_config(target_countries='Italy'),
        defaults to powerplantmatching.config.get_config()

    """
    tech = df["Technology"].dropna()
    if len(tech) == 0:
        return df
    tech = tech.replace({" and ": ", ", " Power Plant": "", "Battery": ""}, regex=True)
    if generalize_hydros:
        tech[tech.str.contains("pump", case=False)] = "Pumped Storage"
        tech[tech.str.contains("reservoir|lake", case=False)] = "Reservoir"
        tech[tech.str.contains("run-of-river|weir|water", case=False)] = "Run-Of-River"
        tech[tech.str.contains("dam", case=False)] = "Reservoir"
    tech = tech.replace({"Gas turbine": "OCGT"})
    tech[tech.str.contains("combined cycle|combustion", case=False)] = "CCGT"
    tech[
        tech.str.contains("steam turbine|critical thermal", case=False)
    ] = "Steam Turbine"
    tech[tech.str.contains("ocgt|open cycle", case=False)] = "OCGT"
    tech = (
        tech.str.title()
        .str.split(", ")
        .apply(lambda x: ", ".join(i.strip() for i in np.unique(x)))
    )
    tech = tech.replace({"Ccgt": "CCGT", "Ocgt": "OCGT"}, regex=True)
    return df.assign(Technology=tech)


def cliques(df, dataduplicates):
    """
    Locate cliques of units which are determined to belong to the same
    powerplant.  Return the same dataframe with an additional column
    "grouped" which indicates the group that the powerplant is
    belonging to.

    Parameters
    ----------
    df : pandas.Dataframe or string
        dataframe or csv-file which should be analysed
    dataduplicates : pandas.Dataframe or string
        dataframe or name of the csv-linkfile which determines the
        link within one dataset
    """
    #    df = read_csv_if_string(df)
    G = nx.DiGraph()
    G.add_nodes_from(df.index)
    G.add_edges_from((r.one, r.two) for r in dataduplicates.itertuples())
    H = G.to_undirected(reciprocal=True)

    grouped = pd.Series(np.nan, index=df.index)
    for i, inds in enumerate(nx.algorithms.clique.find_cliques(H)):
        grouped.loc[inds] = i

    return df.assign(grouped=grouped)


def aggregate_units(
    df,
    dataset_name=None,
    pre_clean_name=True,
    save_aggregation=True,
    country_wise=True,
    use_saved_aggregation=False,
    config=None,
):
    """
    Vertical cleaning of the database. Cleans the "Name"-column, sums
    up the capacity of powerplant units which are determined to belong
    to the same plant.

    Parameters
    ----------
    df : pandas.Dataframe or string
        Dataframe or name to use for the resulting database
    dataset_name : str, default None
        Specify the name of your df, required if use_saved_aggregation is set
        to True.
    pre_clean_name : Boolean, default True
        Whether to clean the 'Name'-column before aggregating.
    use_saved_aggregation : bool (default False):
        Whether to use the automatically saved aggregation file, which
        is stored in data/out/default/aggregations/aggregation_groups_XX.csv
        with XX being the name for the dataset. This saves time if you
        want to have aggregated powerplants without running the
        aggregation algorithm again
    """
    df = get_obj_if_Acc(df)

    if config is None:
        config = get_config()

    if dataset_name is None:
        ds_name = get_name(df)
    else:
        ds_name = dataset_name

    cols = config["target_columns"]
    weighted_cols = {"Efficiency", "Duration"} & set(cols)
    str_cols = {"Name", "Country", "Fueltype", "Technology", "Set"} & set(cols)
    props_for_groups = {k: v for k, v in AGGREGATION_FUNCTIONS.items() if k in cols}

    df = (
        df.assign(**(df[weighted_cols] * df.Capacity))
        .assign(lat=df.lat.astype(float), lon=df.lon.astype(float))
        .assign(**df[str_cols].fillna("").astype(str))
    )

    if pre_clean_name:
        df = clean_name(df)

    logger.info(f"Aggregating blocks to entire units in '{ds_name}'.")
    path_name = _data_out(f"aggregations/aggregation_groups_{ds_name}.csv", config)

    if use_saved_aggregation & save_aggregation:
        if os.path.exists(path_name):
            logger.info(f"Using saved aggregation groups for dataset '{ds_name}'")
            groups = pd.read_csv(path_name, header=None, index_col=0)
            groups = groups.reindex(index=df.index)
            df = df.assign(grouped=groups.values)
        else:
            if "grouped" in df:
                df.drop("grouped", axis=1, inplace=True)
    else:
        logger.info(f"Not using saved aggregation groups for dataset '{ds_name}'.")

    if "grouped" not in df:
        if country_wise:
            countries = df.Country.unique()
            duplicates = pd.concat([duke(df.query("Country == @c")) for c in countries])
        else:
            duplicates = duke(df)
        df = cliques(df, duplicates)
        if save_aggregation:
            df.grouped.to_csv(path_name, header=False)

    df = df.groupby("grouped").agg(props_for_groups)
    df = df.replace("nan", np.nan)

    if "EIC" in df:
        df = df.assign(EIC=df["EIC"].apply(list))

    df = (
        df.assign(**df[weighted_cols].div(df["Capacity"]))
        .reset_index(drop=True)
        .pipe(clean_name)
        .reindex(columns=cols)
        .pipe(set_column_name, ds_name)
    )
    return df
