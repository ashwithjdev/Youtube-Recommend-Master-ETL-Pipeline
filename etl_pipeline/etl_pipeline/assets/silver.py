import polars as pl
import pandas as pd
from datetime import datetime

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.types import IntegerType, StringType
from pyspark.sql.functions import udf, to_timestamp

from ..partitions import monthly_partitions
from ..func_process import replace_str, format_date

from dagster import (
    AssetExecutionContext,
    MetadataValue,
    AssetIn,
    AssetIn,
    Output,
    asset
)


GROUP_NAME = "silver"

@asset(
    ins={
        "bronze_videoCategory_trending": AssetIn(
            key_prefix=["bronze", "youtube"]
        )
    },
    name="silver_videoCategory_cleaned",
    required_resource_keys={"spark_io_manager"},
    io_manager_key="spark_io_manager",
    key_prefix=["silver", "youtube"],
    compute_kind="PySpark",
    group_name=GROUP_NAME
)
def silver_videoCategory_cleaned(context: AssetExecutionContext,
                                 bronze_videoCategory_trending: pl.DataFrame
    ) -> Output[pl.DataFrame]:
    """ 
        Clean 'videoCategory_trending_data' and load to silver layer in MinIO
    """
    spark: SparkSession = context.resources.spark_io_manager.get_spark_session(
        context, "silver_videoCategory_cleaned-{}".format(datetime.today())
    )
    spark_df: DataFrame = spark.createDataFrame(bronze_videoCategory_trending.to_pandas())
    spark_df = spark_df.withColumn("categoryId", spark_df["categoryId"].cast(IntegerType()))
    spark_df = spark_df.orderBy(spark_df["categoryId"])
    polars_df = pl.DataFrame(spark_df.toPandas())
    context.log.info("Get Object Spark Session")
    context.log.info("Convert polars dataframe to pyspark dataframe")
    context.log.info("Sort pyspark dataframe by categoryId column")
    
    return Output(
        value=polars_df,
        metadata={
            "File Name": MetadataValue.text("videoCategory_cleaned.pq"),
            "Number Columns": MetadataValue.int(polars_df.shape[1]),
            "Number Records": MetadataValue.int(polars_df.shape[0])
        }
    )
    
    
@asset(
    ins={
        "bronze_linkVideos_trending": AssetIn(key_prefix=["bronze", "youtube"]),
        "silver_youtube_trending_01": AssetIn(key_prefix=["silver", "youtube"]),
        "silver_youtube_trending_02": AssetIn(key_prefix=["silver", "youtube"]),
    },
    name="silver_linkVideos_cleaned",
    required_resource_keys={"spark_io_manager", "youtube_io_manager"},
    io_manager_key="spark_io_manager",
    key_prefix=["silver", "youtube"],
    compute_kind="PySpark",
    group_name=GROUP_NAME
)
def silver_linkVideos_cleaned(context: AssetExecutionContext,
                                bronze_linkVideos_trending: pl.DataFrame,
                                silver_youtube_trending_01: pl.DataFrame,
                                silver_youtube_trending_02: pl.DataFrame
    ) -> Output[pl.DataFrame]:
    """ 
        Clean 'linkVideos_trending_data' and load to silver layer in MinIO
    """
    spark: SparkSession = context.resources.spark_io_manager.get_spark_session(
        context, "silver_linkVideos_cleaned-{}".format(datetime.today())
    )
    linkVideos: DataFrame = spark.createDataFrame(bronze_linkVideos_trending.to_pandas())
    trending: DataFrame = spark.createDataFrame(silver_youtube_trending_01.to_pandas())
    trending = trending.dropDuplicates(["video_id"])
    context.log.info("Convert polars dataframe to pyspark dataframe")
    context.log.info("Convert pyspark dataframe to View in SQL query")
    spark_df = linkVideos.join(
        trending,
        linkVideos["videoId"] == trending["video_id"],
        how="outer",
    ).select(trending.video_id, linkVideos.link_video)
    polars_df = pl.DataFrame(spark_df.toPandas())
    
    # trending = pl.concat(
    #     [z
    #         silver_youtube_trending_01,
    #         silver_youtube_trending_02
    #     ]
    # )
    
    # bronze_linkVideos_trending = bronze_linkVideos_trending.with_columns(
    #     pl.col('link_video').apply(lambda e: e.replace('"', ''))
    # )
    # trending = trending.unique(subset=["video_id"])
    # polars_df = bronze_linkVideos_trending.join(
    #     trending, 
    #     left_on="videoId", 
    #     right_on="video_id", 
    #     how="outer"
    # ).select(["video_id", "link_video"])
    
    # polars_df = polars_df.with_columns(
    #     pl.when(pl.col("link_video").is_null()).then(pl.format("www.youtube.com/embed/{}", pl.col("video_id")))
    #       .otherwise(pl.col("link_video")).alias("link_video")
    # )

    return Output(
        value=polars_df,
        metadata={
            "File Name": MetadataValue.text("linkVideos_cleaned.pq"),
            "Number Columns": MetadataValue.int(polars_df.shape[1]),
            "Number Records": MetadataValue.int(polars_df.shape[0])
        }
    )
    
    
@asset(
    ins={
        "silver_youtube_trending_01": AssetIn(key_prefix=["silver", "youtube"]),
        "silver_youtube_trending_02": AssetIn(key_prefix=["silver", "youtube"])
    },
    name="silver_trending_cleaned",
    required_resource_keys={"spark_io_manager"},
    io_manager_key="spark_io_manager",
    key_prefix=["silver", "youtube"],
    partitions_def=monthly_partitions,
    compute_kind="PySpark",
    group_name=GROUP_NAME
)
def silver_trending_cleaned(context: AssetExecutionContext,
                          silver_youtube_trending_01: pl.DataFrame,
                          silver_youtube_trending_02: pl.DataFrame
    ) -> Output[pl.DataFrame]:
    """
        Clean 'bronze_youtube_trending_data' and load to silver layer in MinIO
    """
    spark: SparkSession = context.resources.spark_io_manager.get_spark_session(
        context, "silver_trending_cleaned-{}".format(datetime.today())
    )
    trending = pl.concat([silver_youtube_trending_01, silver_youtube_trending_02])
    
    try:
        partition_date_str = context.asset_partition_key_for_output()
        data_by_publishedAt = trending.filter(
            (pl.col("publishedAt").dt.year() == int(partition_date_str[:4])) &
            (pl.col("publishedAt").dt.month() == int(partition_date_str[5:7]))
        )
    except Exception as e:
        raise Exception(f"{e}")

    # data_by_publishedAt = data_by_publishedAt.with_columns(
    #     pl.col('trending_date').apply(lambda e: e.replace('T', ' ').replace('Z', ''))
    # )
    # data_by_publishedAt = data_by_publishedAt.with_columns(
    #     pl.col("trending_date").str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S")
    # )
    # data_by_publishedAt = data_by_publishedAt.with_columns(
    #         pl.when(pl.col("thumbnail_link").is_not_null())
    #           .then(pl.col("thumbnail_link").str.replace("default.jpg", "maxresdefault.jpg"))
    #           .otherwise(pl.col("thumbnail_link")).alias("thumbnail_link")
    # )
    # data_by_publishedAt = data_by_publishedAt.with_columns([
    #     pl.col("categoryId").cast(pl.Int64),
    #     pl.col("view_count").cast(pl.Int64),
    #     pl.col("likes").cast(pl.Int64),
    #     pl.col("dislikes").cast(pl.Int64),
    #     pl.col("comment_count").cast(pl.Int64)
    # ])
    
    # polars_df: pl.DataFrame = data_by_publishedAt
    
    
    spark_df: DataFrame = spark.createDataFrame(data_by_publishedAt.to_pandas())
    
    # publishedAt replace to format date
    date_format = udf(format_date, StringType())
    # spark_df = spark_df.withColumn("publishedAt", date_format(spark_df["publishedAt"]))
    # Convert date type of column publishedAt to datetime data type
    spark_df = spark_df.withColumn("publishedAt", to_timestamp("publishedAt"))
    # Convert date type of column categoryId to integer data type
    spark_df = spark_df.withColumn("categoryId", spark_df["categoryId"].cast(IntegerType()))
    # trending_date replace to format date
    spark_df = spark_df.withColumn("trending_date", date_format(spark_df["trending_date"]))
    # Convert date type of column trending_date to datetime data type
    spark_df = spark_df.withColumn("trending_date", to_timestamp("trending_date"))
    # Convert date type of column view_count to integer data type
    spark_df = spark_df.withColumn("view_count", spark_df["view_count"].cast(IntegerType()))    
    # Convert date type of column likes to integer data type
    spark_df = spark_df.withColumn("likes", spark_df["likes"].cast(IntegerType()))
    # Convert date type of column dislikes to integer data type
    spark_df = spark_df.withColumn("dislikes", spark_df["dislikes"].cast(IntegerType()))
    # Convert date type of column comment_count to integer data type
    spark_df = spark_df.withColumn("comment_count", spark_df["comment_count"].cast(IntegerType()))
    # thumbnail_link replace from default to maxresdefault
    link_convert = udf(replace_str, StringType())
    spark_df = spark_df.withColumn("thumbnail_link", link_convert(spark_df["thumbnail_link"]))
    # context.log.info(f"Data: {spark_df.show(5)}")
    spark_df.unpersist()
    polars_df = pl.DataFrame(spark_df.toPandas())
    
    return Output(
        value=polars_df,
        metadata={
            "file name": MetadataValue.text("trending_cleaned"),
            "Records": MetadataValue.int(polars_df.shape[0]),
            "Columns": MetadataValue.int(polars_df.shape[1])
        }
    )