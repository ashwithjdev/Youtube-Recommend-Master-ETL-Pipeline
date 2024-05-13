import polars as pl
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.types import IntegerType, StringType
from pyspark.sql.functions import udf, to_timestamp

from dagster import asset, AssetExecutionContext
from dagster import Output, MetadataValue
from dagster import AssetIn

from ..partitions import monthly_partitions
from .func_process import replace_str, format_date


GROUP_NAME = "bronze"

@asset(
    ins={
        "videoCategory_trending_data": AssetIn(
            key_prefix=["bronze", "youtube"]
        )
    },
    name="silver_videoCategory_clean",
    required_resource_keys={"spark_io_manager"},
    io_manager_key="spark_io_manager",
    key_prefix=["silver", "youtube"],
    compute_kind="PySpark",
    group_name=GROUP_NAME
)
def silver_videoCategory_clean(context: AssetExecutionContext,
                               videoCategory_trending_data: pl.DataFrame) -> Output[pl.DataFrame]:
    """ 
        Clean 'videoCategory_trending_data' and load to silver layer in MinIO
    """
    spark: SparkSession = context.resources.spark_io_manager.get_spark_session(context)
    spark_df: DataFrame = spark.createDataFrame(videoCategory_trending_data.to_pandas())
    spark_df = spark_df.withColumn("categoryId", spark_df["categoryId"].cast(IntegerType()))
    spark_df = spark_df.orderBy(spark_df["categoryId"])
    polars_df = pl.DataFrame(spark_df.toPandas())
    context.log.info("Get Object Spark Session")
    context.log.info("Convert polars dataframe to pyspark dataframe")
    context.log.info("Sort pyspark dataframe by categoryId column")
    
    return Output(
        value=polars_df,
        metadata={
            "File Name": MetadataValue.text("videoCategory_clean.pq"),
            "Number Columns": MetadataValue.int(polars_df.shape[1]),
            "Number Records": MetadataValue.int(polars_df.shape[0])
        }
    )
    
    
@asset(
    ins={
        "linkVideos_trending_data": AssetIn(
            key_prefix=["bronze", "youtube"]
        ),
        "bronze_youtube_trending_data": AssetIn(
            key_prefix=["bronze", "youtube"]
        )
    },
    # deps=["bronze_youtube_trending_data"],
    name="silver_linkVideos_clean",
    required_resource_keys={"spark_io_manager", "youtube_io_manager"},
    io_manager_key="spark_io_manager",
    key_prefix=["silver", "youtube"],
    compute_kind="PySpark",
    group_name=GROUP_NAME
)
def silver_linkVideos_clean(context: AssetExecutionContext,
                            linkVideos_trending_data: pl.DataFrame,
                            bronze_youtube_trending_data: pl.DataFrame) -> Output[pl.DataFrame]:
    """ 
        Clean 'linkVideos_trending_data' and load to silver layer in MinIO
    """
    spark: SparkSession = context.resources.spark_io_manager.get_spark_session(context)
    pl_data: pl.DataFrame = context.resources.youtube_io_manager.get_DataFrame(context, "video_id")
    linkVideos: DataFrame = spark.createDataFrame(linkVideos_trending_data.to_pandas())
    trending: DataFrame = spark.createDataFrame(pl_data.to_pandas())
    trending = trending.dropDuplicates(["video_id"])
    context.log.info(f"linkVideos: {linkVideos.count(), len(linkVideos.columns)}")
    context.log.info(f"trending: {trending.count(), len(trending.columns)}")
    context.log.info("Convert polars dataframe to pyspark dataframe")
    context.log.info("Convert pyspark dataframe to View in SQL query")
    spark_df = linkVideos.join(
        trending, 
        linkVideos["videoId"] == trending["video_id"], 
        how="full",
    ).select(trending.video_id, linkVideos.link_video)
    context.log.info(f"spark_df: {spark_df.count(), len(spark_df.columns)}")
    polars_df = pl.DataFrame(spark_df.toPandas())
    
    return Output(
        value=polars_df,
        metadata={
            "File Name": MetadataValue.text("linkVideos_clean.pq"),
            "Number Columns": MetadataValue.int(polars_df.shape[1]),
            "Number Records": MetadataValue.int(polars_df.shape[0])
        }
    )
    
    
@asset(
    ins={
        "bronze_youtube_trending_data": AssetIn(
            key_prefix=["bronze", "youtube"]
        )
    },
    name="silver_trending_clean",
    required_resource_keys={"spark_io_manager"},
    io_manager_key="spark_io_manager",
    key_prefix=["silver", "youtube"],
    partitions_def=monthly_partitions,
    compute_kind="PySpark",
    group_name=GROUP_NAME
)
def silver_trending_clean(context: AssetExecutionContext,
                          bronze_youtube_trending_data: pl.DataFrame) -> Output[pl.DataFrame]:
    """ 
        Clean 'bronze_youtube_trending_data' and load to silver layer in MinIO
    """
    spark: SparkSession = context.resources.spark_io_manager.get_spark_session(context)
    spark_df: DataFrame = spark.createDataFrame(bronze_youtube_trending_data.to_pandas())
    # publishedAt replace to format date
    date_format = udf(format_date, StringType())
    spark_df = spark_df.withColumn("publishedAt", date_format(spark_df["publishedAt"]))
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
    polars_df = pl.DataFrame(spark_df.toPandas())
    
    return Output(
        value=polars_df,
        metadata={
            "file name": MetadataValue,
            "Records": MetadataValue.int(polars_df.shape[0]),
            "Columns": MetadataValue.int(polars_df.shape[1])
        }
    )
    