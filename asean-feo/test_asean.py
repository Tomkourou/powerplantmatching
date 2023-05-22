import os
import sys

import pandas as pd
import yaml

working = os.environ.get("", "/some/default")

import powerplantmatching as ppm

with open(
    "/Users/adminuser/Documents/Coding/Modelling/powerplantmatching/asean-feo/config.yaml",
    "r",
) as f:
    config = yaml.safe_load(f)


ppm.powerplants(config=config, from_url=False, update=True).to_csv(
    "test_powerplants.csv"
)
