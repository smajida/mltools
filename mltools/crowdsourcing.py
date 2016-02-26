"""
What:Contains functions for reading from and writing to the Tomnod database.
Author: Kostas Stamatiou
Created: 02/23/2016
Contact: kostas.stamatiou@digitalglobe.com
"""

import geojson
import os
import psycopg2
import psycopg2.extras

from shapely.wkb import loads


# DB parameters:
host = os.getenv( 'DB_HOST', None )
db = os.getenv( 'DB_NAME', None )
user = os.getenv( 'DB_USER', None )
password = os.getenv( 'DB_PASSWORD', None )
port = os.getenv( 'DB_PORT', None )


class DatabaseError(Exception):
    pass


def getConn(host=host,db=db,port=port,user=user,password=password):
    if user == '' or password == '':
        raise DatabaseError('Database username or password not set.')

    conn_string = "host=%s dbname=%s user=%s password=%s" % (host, db, user, password)
    conn = psycopg2.connect(conn_string)
    conn.autocommit = True
    return conn


def getCursor( conn, fetch_array = True ):
    if fetch_array:
    	return conn.cursor()
    else:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def db_fetch( sql, fetch_array = True ):
    conn = getConn()
    cursor = getCursor(conn, fetch_array)
    try:
        cursor.execute( sql )
        r = cursor.fetchall()
        conn.close()
        return r
    except psycopg2.ProgrammingError, e:
        print "Programming error in query:\n%s" % e
        conn.close()
        return 


def train_geojson(schema, 
	              cat_id,
	              max_number, 
	              output_file, 
	              class_name, 
	              min_score=0.95, 
	              min_votes=0
	             ):
	"""Read features from Tomnod campaign and write to geojson.
	   The purpose of this function is to create training data for a machine.
	   Features are read from the DB in decreasing score order.
	   All features are from the same image and of the same class.

       Args:
           schema (str): Campaign schema.
           cat_id (str): Image catalog id.
           max_number (int): Maximum number of features to be read.
           output_file (str): Output file name (extension .geojson).
           class_name (str): Feature class (type in Tomnod jargon) name.
           min_score (float): Only features with score>=min_score will be read.
           min_votes (int): Only features with votes>=min_votes will be read.
	"""

	print 'Retrieve data for: ' 
	print 'Schema: ' + schema
	print 'Catalog id: ' + cat_id
	print 'Class name: ' + class_name

	query = """SELECT feature.id, feature.feature
		       FROM {}.feature, tag_type, overlay
		       WHERE feature.type_id = tag_type.id
		       AND feature.overlay_id = overlay.id
		       AND overlay.catalogid = '{}'
		       AND tag_type.name = '{}'
		       AND feature.score >= {}
		       AND feature.num_votes_total >= {}
		       ORDER BY feature.score DESC LIMIT {}""".format(schema, 
		           	                                          cat_id, 
		           	                                          class_name, 
		           	                                          min_score,
		           	                                          min_votes,
		           	                                          max_number)

	data = DB.db_fetch(query)

	# convert to GeoJSON
	geojson_features = [] 
	for entry in data:
		feature_id, coords_in_hex = entry
		polygon = loads(coords_in_hex, hex=True)
		coords = [list(polygon.exterior.coords)]   # the brackets are dictated
		                                           # by geojson format!!! 
		geojson_feature = geojson.Feature(geometry = geojson.Polygon(coords), 
			                              properties={"id": str(feature_id), 
			                                          "class_name": class_name, 
			                                          "image_name": cat_id})
		geojson_features.append(geojson_feature)
	
	feature_collection = geojson.FeatureCollection(geojson_features)	

	# store
	with open(output_file, 'wb') as f:
		geojson.dump(feature_collection, f)		 	   

	print 'Done!'


def target_geojson(schema, 
	               cat_id,
	               max_number, 
	               output_file, 
	               max_score=1.0,
	               max_votes=0 
	              ):

	"""Read features from Tomnod campaign and write to geojson.
       The purpose of this function is to create target data for a machine.
       Features are read from the DB in increasing score order, nulls first.
       (A feature with null score has not been viewed by a user yet.)
	   
       Args:
           schema (str): Campaign schema.
           cat_id (str): Image catalog id.
           max_number (int): Maximum number of features to be read.
           output_file (str): Output file name (extension .geojson).
           max_score (float): Only features with score<=max_score will be read.
		   max_votes (int): Only features with votes<=max_votes will be read.
	"""

	print 'Retrieve data for: ' 
	print 'Schema: ' + schema
	print 'Catalog id: ' + cat_id

	query = """SELECT feature.id, feature.feature, tag_type.name
			   FROM {}.feature, tag_type, overlay
		       WHERE feature.type_id = tag_type.id
	           AND {}.feature, overlay
	           AND feature.overlay_id = overlay.id
	           AND overlay.catalogid = '{}'
	           AND feature.score <= {}
	           AND feature.num_votes_total <= {}
	           ORDER BY feature.score ASC NULLS FIRST
	           LIMIT {}""".format(schema, 
	       	                      cat_id,  
	       	                      min_score,
	       	                      max_score, 
	       	                      max_number)          

	data = DB.db_fetch(query)

	# convert to GeoJSON
	geojson_features = [] 
	for entry in data:
		feature_id, coords_in_hex, class_name = entry
		polygon = loads(coords_in_hex, hex=True)
		coords = [list(polygon.exterior.coords)]   # the brackets are dictated
		                                           # by geojson format!!! 
		geojson_feature = geojson.Feature(geometry = geojson.Polygon(coords), 
			                              properties={"id": str(feature_id), 
			                                          "class_name": class_name, 
			                                          "image_name": cat_id})
		geojson_features.append(geojson_feature)
	
	feature_collection = geojson.FeatureCollection(geojson_features)	

	# store
	with open(output_file, 'wb') as f:
		geojson.dump(feature_collection, f)		 	   

	print 'Done!'	