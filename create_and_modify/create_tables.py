import asyncio, asyncpg
import glob, os, csv, yaml, argparse, base64, traceback
import numpy as np
import pwinput
from cryptography.fernet import Fernet

parser = argparse.ArgumentParser(description="A script that modifies a table and requires the -t argument.")
parser.add_argument('-p', '--password', default=None, required=False, help="Password to access database.")
parser.add_argument('-k', '--encrypt_key', default=None, required=False, help="The encryption key")
args = parser.parse_args()

print('Creating tables in the database...')
# Database connection parameters
loc = 'dbase_info'
tables_subdir = 'postgres_tables'
table_yaml_file = os.path.join(loc, 'tables_fnal.yaml')
conn_yaml_file = os.path.join(loc, 'conn.yaml')
conn_info = yaml.safe_load(open(conn_yaml_file, 'r'))
db_params = {
    'database': conn_info.get('dbname'),
    'user': 'postgres',
    'host': conn_info.get('db_hostname'),
    'port': conn_info.get('port'),
    'password': 'hgcal'}

if args.password is None:
    dbpassword = pwinput.pwinput(prompt='Enter superuser password: ', mask='*')
else:
    if args.encrypt_key is None:
        print("Encryption key not provided. Exiting..."); exit()
    cipher_suite = Fernet((args.encrypt_key).encode())
    db_params.update({'password': cipher_suite.decrypt( base64.urlsafe_b64decode(args.password)).decode()}) ## Decode base64 to get encrypted string and then decrypt

def get_csv_fname(loc):
    os.chdir(loc)
    fnameLs = glob.glob("*.csv")
    return fnameLs

def get_column_names(col1_list, col2_list, fk_name, fk_ref, parent_table):
    combined_list = []
    for item1, item2 in zip(col1_list, col2_list):
        combined_list.append(f'{item1} {item2}')
    table_columns_with_type = ', '.join(combined_list)
    if fk_name.size != 0:
        table_columns_with_type += f', CONSTRAINT {fk_ref[0]} FOREIGN KEY({fk_name[0]}) REFERENCES {parent_table[0]}({fk_name[0]})'
    return table_columns_with_type

def get_table_info(loc, tables_subdir, fname):
    with open(os.path.join(loc, tables_subdir, fname) , mode='r') as file:
        csvFile = csv.reader(file, quotechar='"')
        rows = []
        for row in csvFile:
            if any(cell.strip() for cell in row):
                rows.append(row)
        columns = np.array(rows).T
        comment_columns = columns[2] 
        fk = columns[0][(np.where(columns[-1] != ''))]
        fk_ref = columns[-2][(np.where(columns[-1] != ''))]
        fk_tab = columns[-1][(np.where(columns[-1] != ''))]
        ### returning table_name, table_header, dat_type, fk_name, fk_ref, parent_table, comment_columns
        return fname.split('.csv')[0], columns[0], columns[1], fk, fk_ref, fk_tab, comment_columns  ### fk, fk_tab are returned as lists

async def create_tables_sequence():
    # Connect to the database
    conn = await asyncpg.connect(**db_params)
    schema_name = 'public'  # Change this if your tables are in a different schema
    print('Connection successful. \n')

    async def create_table(table_name, table_columns_with_type, comment_columns = None, table_headers = None, table_description = None):
        # Check if the table exists
        table_exists_query = f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = $1 AND table_name = $2);"
        table_exists = await conn.fetchval(table_exists_query, schema_name, table_name)
        if not table_exists:
            create_table_query = f""" CREATE TABLE {table_name} ( {table_columns_with_type} ); """
            await conn.execute(create_table_query)
            for t in range(len(table_headers)):
                set_comment_query = f"COMMENT ON COLUMN {table_name}.{table_headers[t]} IS '{comment_columns[t]}';"
                await conn.execute(set_comment_query) 
            print(f"Table '{table_name}' created successfully.")
        else:
            print(f"Table '{table_name}' already exists.")
        if table_description:
            comment_table_query = f""" COMMENT ON TABLE {table_name} IS '{table_description}' ;"""
            await conn.execute(comment_table_query)
            print(f"Table '{table_name}' description updated.")

    async def allow_perm(table_name, permission, user):
        await conn.execute(f"GRANT {permission} ON {table_name} TO {user};")
        print(f"Table '{table_name}' has {permission} access granted to {user}.")

    async def allow_seq_perm(seq_name, user):
        await conn.execute(f"GRANT USAGE ON {seq_name} TO {user};")
        print(f"Sequence '{seq_name}' has USAGE granted to {user}.")

    async def allow_schema_perm(user):
        #await conn.execute(f"GRANT USAGE ON SCHEMA public TO {user};")
        #await conn.execute(f"GRANT SELECT ON information_schema.tables TO {user};")
        print(f"Schema permission access granted to {user}.")

    try:
        ## Define the table name and schema
        with open(table_yaml_file, 'r') as file:
            data = yaml.safe_load(file)
            print('\n')

            for i in data.get('tables'):
                fname = f"{(i['fname'])}"
                table_description = f"{(i['description'])}"
                print(f'Getting info from {fname}...')

                table_name, table_header, dat_type, fk_name, fk_ref, parent_table, comment_columns = get_table_info(loc, tables_subdir, fname)
                table_columns_with_type = get_column_names(table_header, dat_type, fk_name, fk_ref, parent_table)
                await create_table(table_name=table_name, table_columns_with_type=table_columns_with_type, comment_columns=comment_columns, table_headers=table_header, table_description=table_description)
                pk_seq = f'{table_name}_{table_header[0]}_seq'
                        
                # Allow permissions:
                for k in i['permission'].keys():
                    try:
                        await allow_perm(table_name, i['permission'][k], k)
                        if 'INSERT' in i['permission'][k]:
                            await allow_seq_perm(pk_seq, k)
                    except:
                        print(f'Permission {k} already exist.')
                
                print('\n')

        print("Granting UPDATE permission to teststand_user for front_wirebond.wb_fr_marked_done.")
        front_wirebond_done_query = "GRANT UPDATE (wb_fr_marked_done) ON front_wirebond TO teststand_user;"
        await conn.execute(front_wirebond_done_query)

    except asyncpg.PostgresError as e:
        print("Error:", e)
        traceback.print_exc()
    finally:
        await conn.close()

asyncio.run(create_tables_sequence())
