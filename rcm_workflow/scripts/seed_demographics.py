import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.db_config import DB_CONFIG
import pymysql
from datetime import datetime
import json


# =============================================
# STEP 1: Create RCM_CASE Record
# =============================================
def create_demographics_case(cursor, clinic_id=10, patient_id=None):
    insert_query = """
        INSERT INTO RCM_CASE (
            clinic_id,
            patient_id,
            workflow_name,
            case_type,
            state_code,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    values = (
        clinic_id,
        patient_id,              # ──► PATIENT_ID added ✅
        'DEMOGRAPHICS',          # ──► workflow_name
        'DEMOGRAPHICS',          # ──► case_type
        'DEMOGRAPHICS_CREATED',  # ──► state_code
        datetime.now(),
        datetime.now()
    )
    cursor.execute(insert_query, values)
    case_id = cursor.lastrowid

    print(f"   ✅ RCM_CASE created        | case_id       : {case_id}")
    print(f"      clinic_id               : {clinic_id}")
    print(f"      patient_id              : {patient_id}")   # ──► Added ✅
    print(f"      workflow_name           : DEMOGRAPHICS")
    print(f"      case_type               : DEMOGRAPHICS")
    print(f"      state_code              : DEMOGRAPHICS_CREATED")
    return case_id


# =============================================
# STEP 2: Create RCM_CASE_FACT Records
# =============================================
def create_case_facts(cursor, case_id, clinic_id=10, patient_id=None):

    # ──► Use patient_id if provided, else fallback to dummy
    pid = str(patient_id) if patient_id else "PAT-DUMMY-001"

    patient_fact = {
        "PATIENT_ID"    : pid,                  # ──► Dynamic ✅
        "CLINIC_ID"     : str(clinic_id),
        "FIRST_NAME"    : "John",
        "LAST_NAME"     : "Doe",
        "DATE_OF_BIRTH" : "1990-01-15",
        "GENDER"        : "M",
        "SSN"           : "XXX-XX-1234",
        "ADDRESS"       : "123 Main Street",
        "CITY"          : "Austin",
        "STATE"         : "TX",
        "ZIP"           : "78701",
        "PHONE"         : "512-000-0000",
        "EMAIL"         : "john.doe@dummy.com",
        "GUARANTOR_ID"  : "0"
    }

    insurance_fact = {
        "INSURANCE_ID"    : "INS-DUMMY-001",
        "CLINIC_ID"       : str(clinic_id),
        "PATIENT_ID"      : pid,               
        "PAYER_NAME"      : "Dummy Insurance Co",
        "PAYER_ID"        : "DUMMY123",
        "POLICY_NUMBER"   : "POL-000001",
        "GROUP_NUMBER"    : "GRP-000001",
        "SUBSCRIBER_NAME" : "John Doe",
        "SUBSCRIBER_DOB"  : "1990-01-15",
        "RELATIONSHIP"    : "SELF",
        "COVERAGE_START"  : "2024-01-01",
        "COVERAGE_END"    : "2024-12-31",
        "COPAY"           : "20.00",
        "DEDUCTIBLE"      : "1000.00",
        "ELIGIBILITY_CHECK_DATE":"2026-04-04"
    }

    demographics_fact = {
        "PATIENT_ID"         : pid,           
        "CLINIC_ID"          : str(clinic_id),
        "DEMOGRAPHICS_TYPE"  : "PRIMARY",
        "FIRST_NAME"         : "John",
        "LAST_NAME"          : "Doe",
        "MIDDLE_NAME"        : "A",
        "DATE_OF_BIRTH"      : "1990-01-15",
        "GENDER"             : "M",
        "MARITAL_STATUS"     : "SINGLE",
        "RACE"               : "UNKNOWN",
        "ETHNICITY"          : "UNKNOWN",
        "PREFERRED_LANGUAGE" : "ENGLISH",
        "ADDRESS_LINE1"      : "123 Main Street",
        "ADDRESS_LINE2"      : "",
        "CITY"               : "Austin",
        "STATE"              : "TX",
        "ZIP"                : "78701",
        "COUNTY"             : "Travis",
        "PHONE_HOME"         : "512-000-0000",
        "PHONE_MOBILE"       : "512-000-0001",
        "EMAIL"              : "john.doe@dummy.com",
        "EMERGENCY_CONTACT"  : "Jane Doe",
        "EMERGENCY_PHONE"    : "512-000-0002",
        "EMERGENCY_RELATION" : "SPOUSE"
    }

    facts = [
        {
            "fact_key"       : "PATIENT_FACT",
            "fact_value_str" : json.dumps(patient_fact),
            "source"         : "PATIENT_IMPORT"
        },
        {
            "fact_key"       : "INSURANCE_FACT",
            "fact_value_str" : json.dumps(insurance_fact),
            "source"         : "INSURANCE_IMPORT"
        },
        {
            "fact_key"       : "DEMOGRAPHICS_FACT",
            "fact_value_str" : json.dumps(demographics_fact),
            "source"         : "DEMOGRAPHICS_IMPORT"
        }
    ]

    insert_query = """
        INSERT INTO RCM_CASE_FACT (
            clinic_id,
            rcm_case_id,
            fact_key,
            fact_value_str,
            fact_value_num,
            fact_value_bool,
            fact_value_date,
            source,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    inserted_facts = []
    for fact in facts:
        values = (
            clinic_id,
            case_id,
            fact["fact_key"],
            fact["fact_value_str"],
            None,
            None,
            None,
            fact["source"],
            datetime.now()
        )
        cursor.execute(insert_query, values)
        fact_id = cursor.lastrowid

        inserted_facts.append(fact_id)
        print(f"   ✅ RCM_CASE_FACT created   | fact_id : {fact_id:<6} "
              f"| fact_key : {fact['fact_key']:<25} "
              f"| source : {fact['source']}")

    return inserted_facts


# =============================================
# STEP 3: Create RCM_TASK Record
# =============================================
def create_rcm_task(cursor, case_id, clinic_id=10, patient_id=None):

    # ──► Use patient_id if provided, else fallback to dummy
    pid = str(patient_id) if patient_id else "PAT-DUMMY-001"

    insert_query = """
        INSERT INTO RCM_TASK (
            clinic_id,
            rcm_case_id,
            task_type,
            state_code,
            outcome,
            priority_code,
            queue_id,
            owner_user_id,
            opened_at,
            due_at,
            next_action_at,
            handler_key,
            attempt_count,
            payload_json,
            result_json,
            created_at,
            updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s
        )
    """

    values = (
        clinic_id,
        case_id,
        'INITIALIZE_DEMOGRAPHICS',
        'WAITING',
        None,
        'HIGH',
        'INITIALIZE_DEMOGRAPHICS_QUEUE',
        None,
        datetime.now(),
        None,
        None,
        'INITIALIZE_DEMOGRAPHICS_HANDLER',
        0,
        None,
        None,
        datetime.now(),
        datetime.now()
    )

    cursor.execute(insert_query, values)
    task_id = cursor.lastrowid

    print(f"   ✅ RCM_TASK created         | task_id       : {task_id}")
    print(f"      clinic_id               : {clinic_id}")
    print(f"      rcm_case_id             : {case_id}")
    print(f"      patient_id              : {pid}")          # ──► Added ✅
    print(f"      task_type               : INITIALIZE_DEMOGRAPHICS")
    print(f"      state_code              : WAITING")
    print(f"      queue_id                : INITIALIZE_DEMOGRAPHICS_QUEUE")
    print(f"      handler_key             : INITIALIZE_DEMOGRAPHICS_HANDLER")
    print(f"      priority_code           : HIGH")
    print(f"      payload_json            : NULL")
    print(f"      result_json             : NULL")

    return task_id


# =============================================
# Helper: Check Table Columns
# =============================================
def check_table_columns(cursor, table_name):
    cursor.execute(f"DESCRIBE {table_name}")
    columns = cursor.fetchall()
    print(f"\n📋 Columns in {table_name}:")
    print(f"{'Field':<30} {'Type':<20} {'Null':<6} {'Key':<6} {'Default':<15} {'Extra'}")
    print("-"*90)
    for col in columns:
        print(f"{str(col[0]):<30} {str(col[1]):<20} {str(col[2]):<6} "
              f"{str(col[3]):<6} {str(col[4]):<15} {str(col[5])}")
    print()


# =============================================
# Main Execution
# =============================================
def main():
    conn   = None
    cursor = None

    try:
        conn   = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # ──► Configure these values
        clinic_id  = 10
        patient_id = 492046    # ──► Real patient ID ✅
                               # ──► Set to None for dummy

        # ──► STEP 1
        print("\n" + "="*70)
        print("   STEP 1 : Creating RCM_CASE Record")
        print("="*70)
        case_id = create_demographics_case(
            cursor,
            clinic_id  = clinic_id,
            patient_id = patient_id     # ──► Pass patient_id ✅
        )

        # ──► STEP 2
        print("\n" + "="*70)
        print(f"   STEP 2 : Creating RCM_CASE_FACT Records | case_id : {case_id}")
        print("="*70)
        fact_ids = create_case_facts(
            cursor,
            case_id    = case_id,
            clinic_id  = clinic_id,
            patient_id = patient_id     # ──► Pass patient_id ✅
        )

        # ──► STEP 3
        print("\n" + "="*70)
        print(f"   STEP 3 : Creating RCM_TASK Record       | case_id : {case_id}")
        print("="*70)
        task_id = create_rcm_task(
            cursor,
            case_id    = case_id,
            clinic_id  = clinic_id,
            patient_id = patient_id     # ──► Pass patient_id ✅
        )

        conn.commit()

        print("\n" + "="*70)
        print("   ✅ ALL STEPS COMPLETED SUCCESSFULLY!")
        print("="*70)
        print(f"   clinic_id     : {clinic_id}")
        print(f"   patient_id    : {patient_id}")            # ──► Added ✅
        print(f"   RCM_CASE_ID   : {case_id}")
        print(f"   Fact IDs      : {fact_ids}")
        print(f"   RCM_TASK_ID   : {task_id}")
        print("="*70 + "\n")

    except Exception as e:
        print(f"\n❌ Database Error: {e}")
        if conn:
            conn.rollback()

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    main()