from typing import List, Dict, Optional, Any
from app.models.schemas import CodeRequirement


# Categories used by department agents:
#   building_safety, fire, electrical, plumbing, mechanical,
#   accessibility, energy, zoning, public_works, environmental


BUILDING_CODES_DB = {
    "IBC": {
        "version": "2021",
        "requirements": [
            # ---------- BUILDING & SAFETY (structural, occupancy, construction type) ----------
            {"code_id": "IBC-302", "code_name": "International Building Code", "section": "302",
             "description": "Occupancy classification",
             "category": "building_safety", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Structures shall be classified into one or more groups (A, B, E, F, H, I, M, R, S, U) based on use."},
            {"code_id": "IBC-503", "code_name": "International Building Code", "section": "503",
             "description": "Allowable height and area by construction type",
             "category": "building_safety", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Building height and area limitations are determined by Table 504.3 and 506.2 based on occupancy and construction type (I-A through V-B)."},
            {"code_id": "IBC-602", "code_name": "International Building Code", "section": "602",
             "description": "Construction types I-V; fire-resistance ratings for structural elements",
             "category": "building_safety", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Type I, II = noncombustible; Type III = exterior noncombustible, interior any; Type IV = heavy timber; Type V = any material. Fire-resistance ratings per Table 601."},
            {"code_id": "IBC-705", "code_name": "International Building Code", "section": "705",
             "description": "Exterior walls fire-resistance based on fire separation distance",
             "category": "building_safety", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Exterior walls shall have fire-resistance per Table 705.5 based on distance to lot lines and adjacent buildings."},
            {"code_id": "IBC-1004.1", "code_name": "International Building Code", "section": "1004.1",
             "description": "Occupant load calculation per Table 1004.5",
             "category": "building_safety", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": "sf/person", "jurisdiction_specific": False,
             "full_text": "Occupant load determined by dividing floor area by occupant load factor (e.g., 100 sf/occupant for business, 7 sf for assembly fixed seating)."},
            {"code_id": "IBC-1005.1", "code_name": "International Building Code", "section": "1005.1",
             "description": "Minimum corridor width",
             "category": "building_safety", "requirement_type": "dimension",
             "min_value": 44, "max_value": None, "unit": "inches", "jurisdiction_specific": False,
             "full_text": "Corridors serving occupant load > 50 shall be minimum 44 inches wide; serving occupant load ≤ 50 may be 36 inches."},
            {"code_id": "IBC-1006.3.3", "code_name": "International Building Code", "section": "1006.3.3",
             "description": "Minimum two exits per story when occupant load exceeds threshold",
             "category": "building_safety", "requirement_type": "procedure",
             "min_value": 2, "max_value": None, "unit": "exits", "jurisdiction_specific": False,
             "full_text": "Each story shall have a minimum of two exits when occupant load exceeds limits in Table 1006.3.3."},
            {"code_id": "IBC-1010.1.1", "code_name": "International Building Code", "section": "1010.1.1",
             "description": "Egress door minimum clear width",
             "category": "building_safety", "requirement_type": "dimension",
             "min_value": 32, "max_value": None, "unit": "inches", "jurisdiction_specific": False,
             "full_text": "Egress doors shall provide a minimum clear opening width of 32 inches measured with door open 90 degrees."},
            {"code_id": "IBC-1011.5.2", "code_name": "International Building Code", "section": "1011.5.2",
             "description": "Stairway minimum width",
             "category": "building_safety", "requirement_type": "dimension",
             "min_value": 44, "max_value": None, "unit": "inches", "jurisdiction_specific": False,
             "full_text": "Stairways serving occupant load > 50 shall be minimum 44 inches wide. R-3 stairs may be 36 inches."},
            {"code_id": "IBC-1208.2", "code_name": "International Building Code", "section": "1208.2",
             "description": "Minimum ceiling height for occupiable spaces",
             "category": "building_safety", "requirement_type": "dimension",
             "min_value": 7.5, "max_value": None, "unit": "feet", "jurisdiction_specific": False,
             "full_text": "Occupiable spaces shall have ceiling height not less than 7'-6\". Habitable rooms in dwellings may be 7'-0\" minimum."},
            {"code_id": "IBC-1604.3", "code_name": "International Building Code", "section": "1604.3",
             "description": "Structural serviceability and deflection limits",
             "category": "building_safety", "requirement_type": "load",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Floors L/360 live load, roofs L/240, plaster ceilings L/360. Drift limits per ASCE 7."},
            {"code_id": "IBC-1607", "code_name": "International Building Code", "section": "1607",
             "description": "Live loads by occupancy",
             "category": "building_safety", "requirement_type": "load",
             "min_value": None, "max_value": None, "unit": "psf", "jurisdiction_specific": False,
             "full_text": "Live loads per Table 1607.1: residential 40 psf, offices 50 psf, assembly 100 psf, stairs 100 psf."},
        ]
    },

    "IFC": {
        "version": "2021",
        "requirements": [
            # ---------- FIRE ----------
            {"code_id": "IFC-903.2", "code_name": "International Fire Code", "section": "903.2",
             "description": "Automatic sprinkler systems required by occupancy",
             "category": "fire", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Sprinklers required in: Group A > 100 occupants, R occupancies > 2 stories, M > 12,000 sf, S > 12,000 sf, all I occupancies."},
            {"code_id": "IFC-903.3.1", "code_name": "International Fire Code", "section": "903.3.1",
             "description": "Sprinkler installation standards (NFPA 13/13R/13D)",
             "category": "fire", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Sprinklers shall be designed per NFPA 13 (commercial), 13R (multi-family ≤ 4 stories), or 13D (1-2 family dwellings)."},
            {"code_id": "IFC-907.2", "code_name": "International Fire Code", "section": "907.2",
             "description": "Fire alarm and detection systems required",
             "category": "fire", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Manual fire alarm systems required in A (>300), B (>500 or >100 above/below LOD), E (>50), R-1, R-2, R-4, I occupancies."},
            {"code_id": "IFC-906.1", "code_name": "International Fire Code", "section": "906.1",
             "description": "Portable fire extinguishers required",
             "category": "fire", "requirement_type": "procedure",
             "min_value": 75, "max_value": None, "unit": "feet travel distance", "jurisdiction_specific": False,
             "full_text": "Class A fire extinguishers shall be located so travel distance from any point does not exceed 75 feet."},
            {"code_id": "IFC-1006", "code_name": "International Fire Code", "section": "1006",
             "description": "Number of exits and travel distance",
             "category": "fire", "requirement_type": "dimension",
             "min_value": None, "max_value": 200, "unit": "feet", "jurisdiction_specific": False,
             "full_text": "Maximum common path travel: 75-100 ft. Maximum exit access travel: 200 ft (unsprinklered) to 400 ft (sprinklered) depending on occupancy."},
            {"code_id": "IFC-1030.1", "code_name": "International Fire Code", "section": "1030.1",
             "description": "Emergency escape and rescue openings in sleeping rooms",
             "category": "fire", "requirement_type": "dimension",
             "min_value": 5.7, "max_value": None, "unit": "sf net clear", "jurisdiction_specific": False,
             "full_text": "Sleeping rooms below 4th story shall have EERO of min 5.7 sf (5.0 sf at grade), min 24\" height, 20\" width, sill ≤ 44\" AFF."},
            {"code_id": "IFC-503", "code_name": "International Fire Code", "section": "503",
             "description": "Fire apparatus access roads",
             "category": "fire", "requirement_type": "dimension",
             "min_value": 20, "max_value": None, "unit": "feet width", "jurisdiction_specific": False,
             "full_text": "Fire apparatus access roads shall have unobstructed width of 20 ft, vertical clearance of 13'-6\", within 150 ft of all portions of exterior walls."},
            {"code_id": "IFC-507", "code_name": "International Fire Code", "section": "507",
             "description": "Fire hydrant spacing and flow",
             "category": "fire", "requirement_type": "dimension",
             "min_value": 1500, "max_value": None, "unit": "gpm", "jurisdiction_specific": False,
             "full_text": "Fire hydrants per Appendix B/C: residential 1000 gpm @ 20 psi, commercial 1500-4000+ gpm. Spacing 400-600 ft typical."},
        ]
    },

    "NEC": {
        "version": "2023",
        "requirements": [
            # ---------- ELECTRICAL ----------
            {"code_id": "NEC-210.8", "code_name": "National Electrical Code", "section": "210.8",
             "description": "GFCI protection required in wet/damp locations",
             "category": "electrical", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "GFCI required: bathrooms, garages, outdoors, crawl spaces, unfinished basements, kitchens (all 125V 15/20A), laundry, dishwasher branch circuit, within 6 ft of sinks."},
            {"code_id": "NEC-210.12", "code_name": "National Electrical Code", "section": "210.12",
             "description": "AFCI protection in dwelling units",
             "category": "electrical", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "AFCI protection required on all 120V, 15/20A branch circuits supplying outlets in dwelling unit kitchens, family rooms, bedrooms, laundry, hallways, closets."},
            {"code_id": "NEC-210.52", "code_name": "National Electrical Code", "section": "210.52",
             "description": "Receptacle spacing in dwelling units",
             "category": "electrical", "requirement_type": "dimension",
             "min_value": None, "max_value": 12, "unit": "feet", "jurisdiction_specific": False,
             "full_text": "Receptacles spaced so no point along wall is > 6 ft from outlet (12 ft max between outlets). Kitchen countertops: outlet within 24\" of any point along counter > 12\" wide."},
            {"code_id": "NEC-230.70", "code_name": "National Electrical Code", "section": "230.70",
             "description": "Service disconnect location",
             "category": "electrical", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Service disconnect shall be readily accessible, located outside or at nearest point of entrance of service conductors. Max 6 disconnects per service."},
            {"code_id": "NEC-250", "code_name": "National Electrical Code", "section": "250",
             "description": "Grounding and bonding requirements",
             "category": "electrical", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Equipment grounding conductor required for all branch circuits. Grounding electrode system: rod/pipe/plate + bonding to water pipe, structural steel, concrete-encased electrode."},
            {"code_id": "NEC-310.15", "code_name": "National Electrical Code", "section": "310.15",
             "description": "Conductor ampacity",
             "category": "electrical", "requirement_type": "general",
             "min_value": None, "max_value": None, "unit": "amps", "jurisdiction_specific": False,
             "full_text": "Conductors sized per Table 310.16 (e.g., #14 Cu = 15A, #12 = 20A, #10 = 30A, #8 = 50A at 75°C). Apply ambient/bundling derating per 310.15(B)."},
            {"code_id": "NEC-406.4", "code_name": "National Electrical Code", "section": "406.4",
             "description": "Tamper-resistant receptacles in dwelling units",
             "category": "electrical", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "All 125V/15A and 20A receptacles in dwelling units shall be listed tamper-resistant. WR rating required for damp/wet locations."},
        ]
    },

    "IPC": {
        "version": "2021",
        "requirements": [
            # ---------- PLUMBING ----------
            {"code_id": "IPC-403.1", "code_name": "International Plumbing Code", "section": "403.1",
             "description": "Minimum fixture count by occupancy",
             "category": "plumbing", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": "fixtures", "jurisdiction_specific": False,
             "full_text": "Fixture count per Table 403.1: business 1/25 first 50 + 1/50 thereafter; assembly 1/75; residential 1 lav, 1 WC, 1 bath/shower per dwelling."},
            {"code_id": "IPC-405.3.1", "code_name": "International Plumbing Code", "section": "405.3.1",
             "description": "Water closet clearance",
             "category": "plumbing", "requirement_type": "dimension",
             "min_value": 15, "max_value": None, "unit": "inches", "jurisdiction_specific": False,
             "full_text": "Water closets shall have minimum 15 inches centerline-to-wall clearance, 30 inches between fixtures, 21 inches clearance in front."},
            {"code_id": "IPC-604.3", "code_name": "International Plumbing Code", "section": "604.3",
             "description": "Water service pipe sizing",
             "category": "plumbing", "requirement_type": "dimension",
             "min_value": 0.75, "max_value": None, "unit": "inches", "jurisdiction_specific": False,
             "full_text": "Minimum water service pipe size 3/4\" for dwellings. Sized per fixture units and developed length per Tables E103.3.2-3."},
            {"code_id": "IPC-608", "code_name": "International Plumbing Code", "section": "608",
             "description": "Backflow prevention",
             "category": "plumbing", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Backflow preventers required on irrigation, boilers, mechanical equipment, fire sprinkler, dental/medical equipment. Air gap, RPZ, double-check per hazard level."},
            {"code_id": "IPC-906", "code_name": "International Plumbing Code", "section": "906",
             "description": "Drain, waste, vent (DWV) sizing and venting",
             "category": "plumbing", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "DWV pipes sized per drainage fixture units (DFU). Vents required for every trap; minimum vent diameter 1-1/4\"."},
            {"code_id": "IPC-712", "code_name": "International Plumbing Code", "section": "712",
             "description": "Sewer connection slope",
             "category": "plumbing", "requirement_type": "dimension",
             "min_value": 1, "max_value": None, "unit": "% slope", "jurisdiction_specific": False,
             "full_text": "Building sewers 4\" min size, minimum slope 1/8\" per foot (1%) for 4\"+ pipe, 1/4\" per foot for smaller."},
        ]
    },

    "IMC": {
        "version": "2021",
        "requirements": [
            # ---------- MECHANICAL ----------
            {"code_id": "IMC-403.3", "code_name": "International Mechanical Code", "section": "403.3",
             "description": "Outdoor air ventilation rates",
             "category": "mechanical", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": "cfm/person", "jurisdiction_specific": False,
             "full_text": "Outdoor air per Table 403.3.1.1: office 5 cfm/person + 0.06 cfm/sf; classroom 10 cfm/person + 0.12; bedroom 5 cfm/person + 0.06."},
            {"code_id": "IMC-501.3", "code_name": "International Mechanical Code", "section": "501.3",
             "description": "Exhaust ventilation for bathrooms, kitchens, laundry",
             "category": "mechanical", "requirement_type": "procedure",
             "min_value": 50, "max_value": None, "unit": "cfm", "jurisdiction_specific": False,
             "full_text": "Bathroom 50 cfm intermittent / 20 cfm continuous. Kitchen 100 cfm intermittent / 25 cfm continuous (vented hood over range)."},
            {"code_id": "IMC-307.2.1", "code_name": "International Mechanical Code", "section": "307.2.1",
             "description": "Condensate disposal from AC equipment",
             "category": "mechanical", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Condensate shall be conveyed to approved point of disposal. Secondary pan or float switch required if leak would cause damage."},
            {"code_id": "IMC-603", "code_name": "International Mechanical Code", "section": "603",
             "description": "Duct construction and insulation",
             "category": "mechanical", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Supply/return ducts in unconditioned spaces shall be insulated to R-6 (warm climate) to R-8. Sealed per SMACNA standards."},
            {"code_id": "IMC-801", "code_name": "International Mechanical Code", "section": "801",
             "description": "Combustion air for fuel-fired appliances",
             "category": "mechanical", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Combustion air per IFGC. Indoor: 50 cf per 1000 BTU/hr input. Outdoor opening: 1 sq in per 4000 BTU/hr (high) + 1 per 4000 BTU/hr (low)."},
        ]
    },

    "ADA_CBC11B": {
        "version": "2010 ADA + CBC 11B",
        "requirements": [
            # ---------- ACCESSIBILITY ----------
            {"code_id": "ADA-206", "code_name": "ADA Standards", "section": "206",
             "description": "Accessible route required to all accessible elements",
             "category": "accessibility", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "At least one accessible route shall connect accessible site arrival points, parking, accessible building entrance(s), and all accessible spaces."},
            {"code_id": "ADA-403.5", "code_name": "ADA Standards", "section": "403.5",
             "description": "Accessible route minimum clear width",
             "category": "accessibility", "requirement_type": "dimension",
             "min_value": 36, "max_value": None, "unit": "inches", "jurisdiction_specific": False,
             "full_text": "Clear width of accessible route shall be 36 inches minimum, reducible to 32 inches for no more than 24 inches in length."},
            {"code_id": "ADA-404.2.3", "code_name": "ADA Standards", "section": "404.2.3",
             "description": "Door clear width 32 inches",
             "category": "accessibility", "requirement_type": "dimension",
             "min_value": 32, "max_value": None, "unit": "inches", "jurisdiction_specific": False,
             "full_text": "Door openings shall provide clear width of 32 inches minimum (door open 90°)."},
            {"code_id": "ADA-405.2", "code_name": "ADA Standards", "section": "405.2",
             "description": "Ramp maximum slope 1:12",
             "category": "accessibility", "requirement_type": "dimension",
             "min_value": None, "max_value": 8.33, "unit": "%", "jurisdiction_specific": False,
             "full_text": "Ramp slope shall not exceed 1:12 (8.33%). Maximum rise per run 30 inches. Cross slope max 1:48."},
            {"code_id": "ADA-208", "code_name": "ADA Standards", "section": "208",
             "description": "Accessible parking spaces required",
             "category": "accessibility", "requirement_type": "procedure",
             "min_value": 1, "max_value": None, "unit": "spaces", "jurisdiction_specific": False,
             "full_text": "Accessible parking per Table 208.2: 1-25 spaces = 1 accessible; 26-50 = 2; 51-75 = 3; 76-100 = 4. 1 in 6 (min 1) shall be van accessible (96\" + 96\" access aisle)."},
            {"code_id": "ADA-603", "code_name": "ADA Standards", "section": "603",
             "description": "Accessible toilet rooms - clear floor space",
             "category": "accessibility", "requirement_type": "dimension",
             "min_value": 60, "max_value": None, "unit": "inches turning", "jurisdiction_specific": False,
             "full_text": "Toilet room shall provide 60\" turning circle or T-turn. Water closet 60\" wide x 56\" deep clearance with grab bars at 33-36\" AFF."},
            {"code_id": "CBC-11B-202", "code_name": "California Building Code Chapter 11B", "section": "202",
             "description": "Path of travel upgrade triggered by alterations",
             "category": "accessibility", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": True,
             "full_text": "When alterations exceed valuation thresholds, path of travel to altered area (including parking, entrance, restrooms, drinking fountains, signage) must be made accessible."},
        ]
    },

    "ENERGY": {
        "version": "2022 Title 24 / 2021 IECC",
        "requirements": [
            # ---------- ENERGY ----------
            {"code_id": "IECC-C402", "code_name": "International Energy Conservation Code", "section": "C402",
             "description": "Building envelope thermal performance",
             "category": "energy", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Wall, roof, floor, fenestration U-values per Table C402.1.3 by climate zone. Continuous insulation required for steel-framed walls."},
            {"code_id": "IECC-C405", "code_name": "International Energy Conservation Code", "section": "C405",
             "description": "Interior lighting power allowance",
             "category": "energy", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": "W/sf", "jurisdiction_specific": False,
             "full_text": "Interior lighting limited to Table C405.3.2(1) by space type. Daylight harvesting and occupancy sensors required in many spaces."},
            {"code_id": "T24-150", "code_name": "California Title 24 Part 6", "section": "150.1",
             "description": "Residential energy efficiency - mandatory measures",
             "category": "energy", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": True,
             "full_text": "All new residential construction shall meet prescriptive or performance compliance: high-efficacy lighting, HVAC ducts in conditioned space, PV solar required (new SFD)."},
            {"code_id": "CALGREEN-4.106.4", "code_name": "CALGreen", "section": "4.106.4",
             "description": "EV charging infrastructure",
             "category": "energy", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": True,
             "full_text": "New SFD: 1 EV-ready raceway + outlet at 40A 208/240V. Multifamily: 10% EV-capable, 25% EV-ready (2022 update may increase)."},
            {"code_id": "CALGREEN-5.303", "code_name": "CALGreen", "section": "5.303",
             "description": "Water efficiency - low-flow fixtures",
             "category": "energy", "requirement_type": "dimension",
             "min_value": None, "max_value": 1.28, "unit": "gpf WC", "jurisdiction_specific": True,
             "full_text": "Water closets max 1.28 gpf, urinals 0.125 gpf, showerheads 1.8 gpm, lavatories 0.5 gpm (public) / 1.2 gpm (residential)."},
        ]
    },

    "ZONING": {
        "version": "Local",
        "requirements": [
            # ---------- PLANNING / ZONING ----------
            {"code_id": "ZON-SETBACK", "code_name": "Zoning Code", "section": "Setbacks",
             "description": "Required yard setbacks",
             "category": "zoning", "requirement_type": "dimension",
             "min_value": None, "max_value": None, "unit": "feet", "jurisdiction_specific": True,
             "full_text": "Front, side, and rear yard setbacks per zoning district. Typical SFR: front 20-25 ft, side 5-10 ft, rear 15-25 ft."},
            {"code_id": "ZON-HEIGHT", "code_name": "Zoning Code", "section": "Height Limit",
             "description": "Maximum building height",
             "category": "zoning", "requirement_type": "dimension",
             "min_value": None, "max_value": 35, "unit": "feet", "jurisdiction_specific": True,
             "full_text": "Max building height per zoning. Typical residential 30-35 ft. Measured per local definition (avg natural grade to roof midpoint)."},
            {"code_id": "ZON-FAR", "code_name": "Zoning Code", "section": "FAR",
             "description": "Maximum Floor Area Ratio (FAR)",
             "category": "zoning", "requirement_type": "dimension",
             "min_value": None, "max_value": None, "unit": "ratio", "jurisdiction_specific": True,
             "full_text": "FAR = gross floor area / lot area. Typical residential 0.45-0.6; commercial 1.5-4.0."},
            {"code_id": "ZON-LOTCOV", "code_name": "Zoning Code", "section": "Lot Coverage",
             "description": "Maximum lot coverage by structures",
             "category": "zoning", "requirement_type": "dimension",
             "min_value": None, "max_value": 40, "unit": "% of lot", "jurisdiction_specific": True,
             "full_text": "Max % of lot area covered by buildings/impervious. Typical SFR 30-50%."},
            {"code_id": "ZON-PARKING", "code_name": "Zoning Code", "section": "Parking",
             "description": "Required off-street parking",
             "category": "zoning", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": "spaces", "jurisdiction_specific": True,
             "full_text": "Parking ratios by use. SFR: 2 spaces (1 covered). Multifamily: 1-2 per unit. Office: 1 per 250-400 sf. Retail: 1 per 200-300 sf."},
            {"code_id": "ZON-USE", "code_name": "Zoning Code", "section": "Use Permitted",
             "description": "Permitted use in zoning district",
             "category": "zoning", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": True,
             "full_text": "Proposed use must be permitted by-right or conditionally permitted in the zoning district. CUP may be required."},
        ]
    },

    "PUBLIC_WORKS": {
        "version": "Local",
        "requirements": [
            # ---------- PUBLIC WORKS ----------
            {"code_id": "PW-DRIVEWAY", "code_name": "Public Works Standards", "section": "Driveway",
             "description": "Driveway dimensions and approach",
             "category": "public_works", "requirement_type": "dimension",
             "min_value": 10, "max_value": 30, "unit": "feet width", "jurisdiction_specific": True,
             "full_text": "Residential driveway 10-20 ft wide, commercial 24-30 ft. Curb cut permit required; clear sight triangles at intersections."},
            {"code_id": "PW-SIDEWALK", "code_name": "Public Works Standards", "section": "Sidewalk",
             "description": "Sidewalk in public right-of-way",
             "category": "public_works", "requirement_type": "dimension",
             "min_value": 4, "max_value": None, "unit": "feet width", "jurisdiction_specific": True,
             "full_text": "Sidewalk minimum 4 ft wide (5 ft in commercial areas), 4 inches thick concrete on 4\" base. ADA cross-slope max 2%."},
            {"code_id": "PW-GRADING", "code_name": "Public Works / Grading Code", "section": "Grading",
             "description": "Grading permit thresholds",
             "category": "public_works", "requirement_type": "procedure",
             "min_value": 50, "max_value": None, "unit": "cy", "jurisdiction_specific": True,
             "full_text": "Grading permit typically required for cut/fill > 50 cy, slopes > 5 ft height, or imported/exported soil. Engineered grading plan if > 200 cy."},
            {"code_id": "PW-STORMWATER", "code_name": "Stormwater Standards", "section": "MS4 / LID",
             "description": "Stormwater detention and Low Impact Development",
             "category": "public_works", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": True,
             "full_text": "Sites > 1 acre or > 2,500 sf impervious in priority zones require LID/SWQMP. Treat first 0.75\" runoff (or 85th percentile storm)."},
            {"code_id": "PW-ROW-ENCROACH", "code_name": "Public Works", "section": "ROW Encroachment",
             "description": "Right-of-way encroachment permit",
             "category": "public_works", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": True,
             "full_text": "Any improvement in public ROW (driveway approach, sewer lateral, utility tap, sidewalk replacement) requires encroachment permit and bond."},
        ]
    },

    "ENVIRONMENTAL": {
        "version": "Federal/State",
        "requirements": [
            # ---------- ENVIRONMENTAL ----------
            {"code_id": "ENV-SWPPP", "code_name": "NPDES / SWPPP", "section": "Construction General Permit",
             "description": "SWPPP for sites disturbing ≥ 1 acre",
             "category": "environmental", "requirement_type": "procedure",
             "min_value": 1, "max_value": None, "unit": "acre", "jurisdiction_specific": False,
             "full_text": "Sites disturbing ≥ 1 acre (or part of common plan ≥ 1 acre) require NOI under Construction General Permit and a SWPPP with BMPs."},
            {"code_id": "ENV-CBC-7A", "code_name": "California Building Code Ch. 7A", "section": "7A",
             "description": "Wildland-Urban Interface (WUI) construction",
             "category": "environmental", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": True,
             "full_text": "Buildings in SRA/LRA Fire Hazard Severity Zones (Moderate/High/Very High) shall use ignition-resistant construction: Class A roof, ember-resistant vents, dual-glazed windows, noncombustible siding within 5 ft."},
            {"code_id": "ENV-DEFENSIBLE", "code_name": "PRC 4291 / CCR 14 §1299", "section": "Defensible Space",
             "description": "Defensible space 100 ft in WUI",
             "category": "environmental", "requirement_type": "dimension",
             "min_value": 100, "max_value": None, "unit": "feet", "jurisdiction_specific": True,
             "full_text": "Zone 0 (0-5 ft): ember-resistant. Zone 1 (5-30 ft): lean, clean, green. Zone 2 (30-100 ft): reduced fuel."},
            {"code_id": "ENV-LEAD", "code_name": "EPA RRP Rule", "section": "40 CFR 745",
             "description": "Lead-safe work practices in pre-1978 buildings",
             "category": "environmental", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Renovations disturbing > 6 sf interior / 20 sf exterior in pre-1978 buildings require EPA-certified renovator and lead-safe practices."},
            {"code_id": "ENV-ASBESTOS", "code_name": "NESHAP / Cal/OSHA", "section": "Asbestos",
             "description": "Asbestos survey before demolition/renovation",
             "category": "environmental", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": False,
             "full_text": "Pre-demolition asbestos survey required for buildings built before 1981. Notification to AQMD 10 working days before demo."},
        ]
    },
}

# State-specific amendments (carried over from prior version)
STATE_AMENDMENTS = {
    "CA": {
        "seismic_zone": "D",
        "code_title": "California Building Code (CBC)",
        "amendments": [
            {"code_id": "CBC-1613", "code_name": "California Building Code", "section": "1613",
             "description": "Seismic design - Zone D (high hazard)",
             "category": "building_safety", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": True,
             "full_text": "Zone D structures designed per ASCE 7 Ch. 12. Shear walls, hold-downs, continuous load path required."},
            {"code_id": "CBC-7A-WUI", "code_name": "California Building Code", "section": "7A",
             "description": "Wildland-Urban Interface fire construction",
             "category": "environmental", "requirement_type": "procedure",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": True,
             "full_text": "SRA/LRA fire severity zones require CBC 7A: Class A roof, ember-resistant vents, dual-glazed windows, ignition-resistant siding."},
        ],
        "city_amendments": {
            "Los Angeles": [
                {"code_id": "LABC-91.1600", "code_name": "Los Angeles Building Code", "section": "91.1600",
                 "description": "Soft-story retrofit",
                 "category": "building_safety", "requirement_type": "procedure",
                 "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": True,
                 "full_text": "Soft, weak, or open-front wood-frame buildings shall be evaluated and retrofitted."},
            ],
        }
    },
    "FL": {
        "wind_zone": "III",
        "code_title": "Florida Building Code (FBC)",
        "amendments": [
            {"code_id": "FBC-1609", "code_name": "Florida Building Code", "section": "1609",
             "description": "Wind load - HVHZ",
             "category": "building_safety", "requirement_type": "procedure",
             "min_value": 130, "max_value": None, "unit": "mph", "jurisdiction_specific": True,
             "full_text": "HVHZ buildings designed for wind per ASCE 7 + FBC 1609. Hurricane straps, impact-resistant glazing."},
        ],
    },
    "NY": {
        "amendments": [
            {"code_id": "NYBC-2022", "code_name": "NYC Building Code", "section": "General",
             "category": "building_safety", "requirement_type": "procedure",
             "description": "NYC adopts its own Building Code based on IBC with local amendments",
             "min_value": None, "max_value": None, "unit": None, "jurisdiction_specific": True,
             "full_text": "NYC projects file with DOB; NYC Energy Conservation Code and Local Laws apply."},
        ],
    },
}

CODE_VERSIONS = {
    "CA": "2022 California Building Code (CBC)",
    "FL": "2023 Florida Building Code (FBC)",
    "TX": "2021 International Building Code (with Texas amendments)",
    "NY": "2022 New York City Building Code",
    "WA": "2021 Washington State Building Code",
    "IL": "2021 International Building Code (with Illinois amendments)",
    "DEFAULT": "2021 International Building Code (IBC)",
}


class CodeDatabase:
    """Mock code database providing building code requirements by category."""

    def get_applicable_codes(
        self,
        state: Optional[str],
        city: Optional[str],
        plan_type: str = "commercial",
    ) -> List[CodeRequirement]:
        requirements: List[CodeRequirement] = []
        for code_set in BUILDING_CODES_DB.values():
            for req in code_set["requirements"]:
                requirements.append(CodeRequirement(**req))

        if state and state.upper() in STATE_AMENDMENTS:
            state_data = STATE_AMENDMENTS[state.upper()]
            for req in state_data.get("amendments", []):
                requirements.append(CodeRequirement(**req))

            if city:
                for city_key, city_reqs in state_data.get("city_amendments", {}).items():
                    if city_key.lower() in city.lower():
                        for req in city_reqs:
                            requirements.append(CodeRequirement(**req))

        return requirements

    def get_codes_by_category(
        self,
        category: str,
        state: Optional[str],
        city: Optional[str],
        plan_type: str = "commercial",
    ) -> List[CodeRequirement]:
        return [r for r in self.get_applicable_codes(state, city, plan_type) if r.category == category]

    def get_jurisdiction_amendments(self, state: Optional[str], city: Optional[str]) -> List[str]:
        amendments = []
        if not state:
            return amendments
        s = state.upper()
        if s == "CA":
            amendments += ["CALGreen Code applies", "Title 24 Energy Code applies"]
            if city and "los angeles" in city.lower():
                amendments.append("LADBS requirements apply")
            if city and ("altadena" in city.lower() or "pasadena" in city.lower()):
                amendments.append("LA County Building & Safety jurisdiction")
                amendments.append("CBC Chapter 7A (WUI) applies — Eaton Fire rebuild zone")
        elif s == "FL":
            amendments += ["Florida Building Code applies", "HVHZ wind requirements may apply"]
        elif s == "NY":
            amendments += ["NYC Building Code applies (not IBC)", "NYC Energy Conservation Code applies"]
        return amendments

    def get_code_version(self, state: Optional[str]) -> str:
        if not state:
            return CODE_VERSIONS["DEFAULT"]
        return CODE_VERSIONS.get(state.upper(), CODE_VERSIONS["DEFAULT"])
