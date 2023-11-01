import argparse
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional

from colorama import Fore, Style
from osgeo import gdal
from yirgacheffe.layers import RasterLayer

gdal.UseExceptions()
gdal.SetConfigOption('CPL_LOG', '/dev/null')

class Result(Enum):
    SUCCESS=1
    WARNING=2
    FAIL=3

@dataclass
class ReportEntry:
    key: str
    left_value: Any
    right_value: Any
    success: Result
    notes: str

def gdal_datatype_to_str(gdt: int) -> str:
    if gdal.GDT_Byte == gdt:
        return "byte"
    if gdal.GDT_Int8 == gdt:
        return "int 8"
    if gdal.GDT_Int16 == gdt:
        return "int 16"
    if gdal.GDT_Int32 == gdt:
        return "int 32"
    if gdal.GDT_Int64 == gdt:
        return "int 64"
    if gdal.GDT_UInt16 == gdt:
        return "unsigned int 16"
    if gdal.GDT_UInt32 == gdt:
        return "unsigned int 32"
    if gdal.GDT_Int64 == gdt:
        return "unsigned int 64"
    if gdal.GDT_Float32 == gdt:
        return "float 32"
    if gdal.GDT_Float64 == gdt:
        return "float 64"
    if gdal.GDT_CFloat32 == gdt:
        return "complex float 32"
    if gdal.GDT_CFloat64 == gdt:
        return "complex float 64"
    if gdal.GDT_CInt16 == gdt:
        return "complex int 16"
    if gdal.GDT_CInt32 == gdt:
        return "complex int 32"
    if gdal.GDT_TypeCount == gdt:
        return "type count"
    if gdal.GDT_Unknown == gdt:
        return "gdal unknown"
    return "actual unknown"

def geodiff(
    left_file_path: str,
    right_file_path: str,
    save_raster_path: Optional[str],
) -> List[ReportEntry]:
    report = {
        "left": left_file_path,
        "right": right_file_path,
        "report": []
    }

    left = RasterLayer.layer_from_file(left_file_path)
    right = RasterLayer.layer_from_file(right_file_path)

    same_scale = left.pixel_scale == right.pixel_scale
    report["report"].append(ReportEntry(
        key="Pixel Scale",
        left_value=left.pixel_scale,
        right_value=right.pixel_scale,
        success=Result.SUCCESS if same_scale else Result.FAIL,
        notes="Pass" if same_scale else "Pixel matching will not be attepted"
    ))

    same_projection = left.projection == right.projection
    report["report"].append(ReportEntry(
        key="Projection",
        left_value=left.projection,
        right_value=right.projection,
        success=Result.SUCCESS if same_projection else Result.FAIL,
        notes="Pass" if same_projection else "Pixel matching will not be attempted"
    ))

    same_datatype = left.datatype == right.datatype
    report["report"].append(ReportEntry(
        key="Data type",
        left_value=gdal_datatype_to_str(left.datatype),
        right_value=gdal_datatype_to_str(right.datatype),
        success=Result.SUCCESS if same_datatype else Result.WARNING,
        notes="Pass" if same_datatype else "Pixel matching results will be suspect"
    ))

    same_area = left.area == right.area
    report["report"].append(ReportEntry(
        key="Area",
        left_value=left.area,
        right_value=right.area,
        success=Result.SUCCESS if same_area else Result.WARNING,
        notes="Pass" if same_area else "Pixel matching only for overlapping area"
    ))

    try:
        intersection = RasterLayer.find_intersection([left, right])
    except ValueError:
        intersection = None
    report["report"].append(ReportEntry(
        key="Intersection",
        left_value=left.area,
        right_value=right.area,
        success=Result.SUCCESS if intersection is not None else Result.FAIL,
        notes="Pass" if intersection is not None else "Pixel matching will not be attempted"
    ))

    # Metadata comparisons over, so return early if we can't do anything
    # with matching pixels
    if (not same_scale) or (not same_projection) or (intersection is None):
        return report

    left.set_window_for_intersection(intersection)
    right.set_window_for_intersection(intersection)

    diff_save_name = None
    if save_raster_path is not None:
        _, left_filename = os.path.split(left_file_path)
        diff_save_name = os.path.join(save_raster_path, left_filename)
    diff_layer = RasterLayer.empty_raster_layer_like(
        left,
        filename=diff_save_name,
        datatype=gdal.GDT_Byte,
        nbits=1
    )
    diff_calc = left.numpy_apply(lambda left, right: left != right, right)
    sum = diff_calc.save(diff_layer, and_sum=True)

    report["report"].append(ReportEntry(
        key="Pixel diff count",
        left_value=(float(sum) / (left.window.xsize * left.window.ysize)) * 100 ,
        right_value=None,
        success=Result.SUCCESS if sum == 0 else Result.FAIL,
        notes="Pass" if sum == 0 else "Different pixel values found (percentage)"
    ))

    return report

def pretty_print_report(report:dict) -> None:
    print(f"left: {report['left']}")
    print(f"right: {report['right']}")

    for report in report["report"]:
        print(f"{report.key}: ", end='')
        if Result.SUCCESS == report.success:
            print(f"{Fore.GREEN}SUCCESS{Style.RESET_ALL}")
        elif Result.WARNING == report.success:
            print(f"{Fore.YELLOW}WARNING!{Style.RESET_ALL}")
        elif Result.FAIL == report.success:
            print(f"{Fore.RED}FAIL!!{Style.RESET_ALL}")
        else:
            print("UNKNOWN RESULT")

        if Result.SUCCESS != report.success:
            print(f"\t{report.notes}")
            if report.right_value is not None:
                print(f"\tLeft: {report.left_value}")
                print(f"\tRight: {report.right_value}")
            else:
                print(f"\tDifference: {report.left_value}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Diffs GeoTIFFs")
    parser.add_argument(
        "--left",
        type=str,
        help="GeoTIFF or folder of GeoTIFFs",
        required=True,
        dest="left_path",
    )
    parser.add_argument(
        "--right",
        type=str,
        help="GeoTIFF or folder of GeoTIFFs",
        required=True,
        dest="right_path",
    )
    parser.add_argument(
        "--save-diff-raster",
        type=str,
        help="Path of directory where to save the diff between rasters if possible",
        required=False,
        default=None,
        dest="save_raster_path"
    )
    args = parser.parse_args()

    if args.save_raster_path is not None:
        os.makedirs(args.save_raster_path, exist_ok=True)

    # TODO: Add support for folders
    report = geodiff(args.left_path, args.right_path, args.save_raster_path)

    # TODO: Add option to save report as JSON
    pretty_print_report(report)

if __name__ == "__main__":
    main()
