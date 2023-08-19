import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from mpl_toolkits.axes_grid1 import make_axes_locatable
import numpy as np
import xarray as xr
import argparse
import pandas as pd
from datetime import datetime, date, timedelta
import resource
import os
import time
import yaml
import eurec4a
from collections import defaultdict
from functools import reduce


# Get flight segments
with open('/home/m/m300931/gogoesgone/scripts/all_flights.yaml', 'r') as f:
    meta = yaml.load(f, Loader=yaml.SafeLoader)
    
# Access EUREC4A catalog
cat = eurec4a.get_intake_catalog(use_ipfs=False)
# Get JOANNE dataset
ds = cat.dropsondes.JOANNE.level3.to_dask()


def get_dropsonde_data(flight_day):
    
    year = flight_day.year
    month = flight_day.month
    day = flight_day.day
    
    # Access EUREC4A catalog
    cat = eurec4a.get_intake_catalog(use_ipfs=False)
    ds = cat.dropsondes.JOANNE.level3.to_dask()
    
    # Make dataset of sondes for specific day
    mask_sondes = (ds.launch_time.astype("<M8[D]") == np.datetime64(flight_day)) & (ds.platform_id == "HALO")
    ds_sondes = ds.isel(sonde_id=mask_sondes.compute())
    
    # Get flight segments
    meta = eurec4a.get_flight_segments()

    segments = [{**s,
                 "platform_id": platform_id,
                 "flight_id": flight_id
                }
                for platform_id, flights in meta.items()
                for flight_id, flight in flights.items()
                for s in flight["segments"]
               ]

    segments_by_segment_id = {s["segment_id"]: s for s in segments}
    segments_ordered_by_start_time = list(sorted(segments, key=lambda s: s["start"]))

    circles = [s["segment_id"]
                     for s in segments_ordered_by_start_time
                     if "circle" in s["kinds"]
                     and s["start"].date() == date(year,month,day)
                     and s["platform_id"] == "HALO"
                    ]
    
    # Make dictionary of sondes corresponding to each circle
    sondes = defaultdict(dict)
    for circle in circles:
        sondes[circle] = ds.isel(sonde_id=reduce(lambda a, b: a | b, [ds.sonde_id==d
                                for d in segments_by_segment_id[circle]["dropsondes"]["GOOD"]]))

    return(sondes)

def get_nearest_circle(sonde_dict, target_time):
    
    # Find the dataset with the mean time closest to the target time
    
    # Initialize variables to keep track of the closest dataset and time difference
    closest_circle = None
    closest_time_difference = timedelta.max # Initialize with positive infinity

    # Iterate through the dictionary to find the closest dataset
    for circle, dataset in sonde_dict.items():
        mean_launch_time = dataset.launch_time.mean().values  # Extracting the datetime64[ns] value
        launch_time_datetime = pd.to_datetime(mean_launch_time)#.tolist()#(datetime)  # Convert to Python datetime

        time_difference = abs(launch_time_datetime - target_time)

        if time_difference < closest_time_difference:
            closest_circle = circle
            closest_time_difference = time_difference

    if closest_circle is not None:
        closest_dataset = sonde_dict[closest_circle]
        #print(f"Closest circle: {closest_circle}")
        #print(f"Mean launch_time of closest dataset: {closest_dataset.launch_time.mean()}")
    else:
        print("No flight dataset found in the dictionary.")
        closest_dataset = None

    return(closest_dataset)


def main():

    """
    Plot satellite images, optionally with HALO trajectories. Using code from HALO-DROPS.
    """
    
    parser = argparse.ArgumentParser()
    parser.add_argument("date")
    args = parser.parse_args()
    
    print(f"Plotting satellite images for {args.date}")

    channel = 2
    product = "ABI-L2-CMIPF"
    satellite = "goes16"
    extent = (-60,-50,11,16)
    
    starttime = time.time()
    print("Processing started ", datetime.now())

    # Plotting parameters
    if channel == 2:
        cmin = 0
        cmax = 0.2
        use_cmap = "Greys_r"
        save_path = "/scratch/m/m300931/data/GOES-16/snapshots/channel_2/"

    elif channel == 13:
        cmin = 280
        cmax = 297
        use_cmap = "Greys"
        save_path = "/scratch/m/m300931/data/GOES-16/snapshots/channel_13/"
        
    # Load subset data to plot
    subset_filepath = f"/scratch/m/m300931/data/GOES-16/CMI/channel_{channel}/CMI_subset_{args.date}_{satellite}_{product}_{channel}.nc"
    subset = xr.open_dataset(subset_filepath)

    for i, t in enumerate(subset.t):
        
        print(t.values)
        
        save_file = f"{satellite}_{product}_ch{channel}_{np.datetime_as_string(t.values, unit='s')}.png"
        
        # Check if file already exists
        if os.path.isfile(save_path+save_file):
            print("File already exists:", save_file)
            continue

        fig = plt.figure(figsize=(8,5))
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
        
        # Plot satellite image
        im_sat = subset.CMI.isel(t=i).plot(ax=ax,x='lon',y='lat',cmap=use_cmap,add_colorbar=False,vmin=cmin,vmax=cmax)
        ax.set_extent(extent, crs=ccrs.PlateCarree())
        ax.coastlines(resolution='10m', color='red', linewidth=1)
        
        # Plot dropsondes and flight trajectory            
        date_object = datetime.strptime(args.date, '%Y%m%d')
        sondes = get_dropsonde_data(date_object)
        ds_flight = get_nearest_circle(sondes, t.values)

        # Plot flight path if flight data is not None
        
        if ds_flight is not None:
            ax.plot(
                ds_flight["lon"].isel(alt=-700),
                ds_flight["lat"].isel(alt=-700),
                c="yellow",
                linestyle=":",
                transform=ccrs.PlateCarree(),
                zorder=1,
            )
            # Plot launch locations
            im_launches = ax.scatter(
                ds_flight["lon"].isel(alt=-700),
                ds_flight["lat"].isel(alt=-700),
                marker="o",
                edgecolor="grey",
                s=60,
                transform=ccrs.PlateCarree(),
                c="green")

        plt.title(t.values)
        plt.show()

        plt.savefig(save_path+save_file, dpi=300, bbox_inches="tight")
        plt.close()

    # Check time and memory urage
    print("time:", (time.time() - starttime)/60, "min")
    print("memory usage:", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "Kb")
        
if __name__ == "__main__":
    main()