import streamlit as st
import os
import tempfile
import gc
import base64
import time
import yaml

from tqdm import tqdm
from scrapper import *
from dotenv import load_dotenv
load_dotenv()

from crewai import Crew, Agent, Task, LLM, Process
from crewai_tools import FileReadTool

docs_tool = FileReadTool()
brightdata_tool = os.getenv("BRIGHT_DATA_API_KEY")

@st.cache_resource
def load_llm():
  llm = LLM(model="custom_openai/deepseek-reasoner", base_url="https://api.deepseek.com", api_key=os.getenv("DEEPSEEK_API_KEY"))
  return llm


def create_agents_and_tasks():
    """Creates a Crew for analysis of the channel scrapped output"""

    with open("config.yaml", 'r') as file:
        config = yaml.safe_load(file)
    
    analysis_agent = Agent(
        role=config["agents"][0]["role"],
        goal=config["agents"][0]["goal"],
        backstory=config["agents"][0]["backstory"],
        verbose=True,
        tools=[docs_tool],
        llm=load_llm()
    )

    comparison_agent = Agent(
        role=config["agents"][1]["role"],
        goal=config["agents"][1]["goal"],
        backstory=config["agents"][1]["backstory"],
        verbose=True,
        tools=[docs_tool],
        llm=load_llm()
    )

    response_synthesizer_agent = Agent(
        role=config["agents"][2]["role"],
        goal=config["agents"][2]["goal"],
        backstory=config["agents"][2]["backstory"],
        verbose=True,
        llm=load_llm()
    )

    analysis_task = Task(
        description=config["tasks"][0]["description"],
        expected_output=config["tasks"][0]["expected_output"],
        agent=analysis_agent
    )

    competitors_task = Task(
        description=config["tasks"][0]["description"],
        expected_output=config["tasks"][0]["expected_output"],
        agent=analysis_agent
    )

    competitor_analysis_task = Task(
        description=config["tasks"][0]["description"],
        expected_output=config["tasks"][0]["expected_output"],
        agent=analysis_agent
    )

    response_task = Task(
        description=config["tasks"][1]["description"],
        expected_output=config["tasks"][1]["expected_output"],
        agent=response_synthesizer_agent
    )

    crew = Crew(
        agents=[analysis_agent, comparison_agent, response_synthesizer_agent],
        tasks=[analysis_task, competitors_task, competitor_analysis_task, response_task],
        process=Process.sequential,
        verbose=True
    )
    return crew


# def create_prod_analysis_agent():
#   pass

# def create_content_agent():
#   pass

# def create_report():
#   pass



# ===========================
#   Streamlit Setup
# ===========================

st.markdown("""# Product Analyst powered by CrewAI and Bright Data For Scrapping""")


if "messages" not in st.session_state:
    st.session_state.messages = []  # Chat history

if "response" not in st.session_state:
    st.session_state.response = None

# if "products" not in st.session_state:
#     st.session_state.products = []

if "crew" not in st.session_state:
    st.session_state.crew = None      # Store the Crew object

def reset_chat():
    st.session_state.messages = []
    gc.collect()


def start_analysis():
    # Create a status container
    with st.spinner('Scraping product data... This may take a moment.'):
        status_container = st.empty()
        status_container.info("Extracting product data from the internet...")
        # Trigger scraping for competitor products
        product_snapshot_id = trigger_scraping_products(
            bright_data_api_key,
            st.session_state.products,
            10,
            st.session_state.start_date,
            st.session_state.end_date,
            "Latest",
            ""
        )
        status = get_progress(bright_data_api_key, product_snapshot_id['snapshot_id'])

        while status['status'] != "ready":
            status_container.info(f"Current status: {status['status']}")
            time.sleep(10)
            status = get_progress(bright_data_api_key, product_snapshot_id['snapshot_id'])

            if status['status'] == "failed":
                status_container.error(f"Scraping failed: {status}")
                return

        if status['status'] == "ready":
            status_container.success("Scraping completed successfully!")
            product_data = get_output(bright_data_api_key, status['snapshot_id'], format="json")

            st.markdown("## Product Data Extracted")
            # Create a container for the carousel of products
            carousel_container = st.container()
            products_per_row = 3

            with carousel_container:
                num_products = len(product_data[0])
                num_rows = (num_products + products_per_row - 1) // products_per_row

                for row in range(num_rows):
                    cols = st.columns(products_per_row)
                    for col_idx in range(products_per_row):
                        product_idx = row * products_per_row + col_idx
                        if product_idx < num_products:
                            with cols[col_idx]:
                                product_item = product_data[0][product_idx]
                                # Display product image if available; otherwise show product name
                                if 'image_url' in product_item and product_item['image_url']:
                                    st.image(product_item['image_url'], use_column_width=True)
                                st.markdown(f"**{product_item.get('product_name', 'Unnamed Product')}**")

            status_container.info("Processing product details...")
            st.session_state.all_files = []
            # Save product details to files for further analysis
            for i in tqdm(range(len(product_data[0]))):
                product_item = product_data[0][i]
                product_id = product_item.get('id', f"product_{i}")
                file = "descriptions/" + product_id + ".txt"
                st.session_state.all_files.append(file)

                with open(file, "w") as f:
                    f.write(f"Product Name: {product_item.get('product_name', 'N/A')}\n")
                    f.write(f"Price: {product_item.get('price', 'N/A')}\n")
                    f.write(f"Description: {product_item.get('description', 'No description available.')}\n")
                    if 'features' in product_item:
                        f.write("Features:\n")
                        for feature in product_item['features']:
                            f.write(f" - {feature}\n")

            st.session_state.product_data = product_data
            status_container.success("Scraping complete! We shall now analyze the product data and report trends...")
        else:
            status_container.error(f"Scraping failed with status: {status}")

    if status['status'] == "ready":
        status_container = st.empty()
        with st.spinner('The agent is analyzing the product data... This may take a moment.'):
            # Create crew and kick off the analysis task using the product details
            st.session_state.crew = create_agents_and_tasks()
            st.session_state.response = st.session_state.crew.kickoff(
                inputs={"file_paths": ", ".join(st.session_state.all_files), "product": ", ".join(st.session_state.all_files)}
            )


# ===========================
#   Sidebar
# ===========================
with st.sidebar:
    st.header("Product Analyst")

    # Initialize the competitors list in session state if it doesn't exist
    if "products" not in st.session_state:
        st.session_state.products = [""]  # Start with one empty field

    # Function to add new competitor product field
    def add_competitor_field():
        st.session_state.products.append("")

    # Create input fields for each competitor product URL
    for i, competitor in enumerate(st.session_state.products):
        col1, col2 = st.columns([6, 1])
        with col1:
            st.session_state.products[i] = st.text_input(
                "Product URL",
                value=competitor,
                key=f"product_{i}",
                label_visibility="collapsed"
            )
        with col2:
            if i > 0:
                if st.button("❌", key=f"remove_{i}"):
                    st.session_state.products.pop(i)
                    st.rerun()

    # Add competitor product button
    st.button("Add Product ➕", on_click=add_competitor_field)

    st.divider()

    st.subheader("Date Range")
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date")
        st.session_state.start_date = start_date.strftime("%Y-%m-%d")
    with col2:
        end_date = st.date_input("End Date")
        st.session_state.end_date = end_date.strftime("%Y-%m-%d")

    st.divider()
    st.button("Start Analysis 🚀", type="primary", on_click=start_analysis)


# ===========================
#   Main Chat Interface
# ===========================
if st.session_state.response:
    with st.spinner('Generating analysis... This may take a moment.'):
        try:
            result = st.session_state.response
            st.markdown("### Generated Analysis")
            st.markdown(result)

            # Add download button for the analysis report
            st.download_button(
                label="Download Content",
                data=result.raw,
                file_name=f"product_analysis.md",
                mime="text/markdown"
            )
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")

# Footer
st.markdown("---")
st.markdown("Built with CrewAI, Bright Data and Streamlit")


# def start_analysis():
#     # Create a status container
    
    
#     with st.spinner('Scraping videos... This may take a moment.'):

#         status_container = st.empty()
#         status_container.info("Extracting data from the internet...")
#         channel_snapshot_id = trigger_scraping_channels(bright_data_api_key, st.session_state.competitors, 10, st.session_state.start_date, st.session_state.end_date, "Latest", "")
#         status = get_progress(bright_data_api_key, channel_snapshot_id['snapshot_id'])

#         while status['status'] != "ready":
#             status_container.info(f"Current status: {status['status']}")
#             time.sleep(10)
#             status = get_progress(bright_data_api_key, channel_snapshot_id['snapshot_id'])

#             if status['status'] == "failed":
#                 status_container.error(f"Scraping failed: {status}")
#                 return
        
#         if status['status'] == "ready":
#             status_container.success("Scraping completed successfully!")

#             # Show a list of YouTube vidoes here in a scrollable container
            
#             channel_scrapped_output = get_output(bright_data_api_key, status['snapshot_id'], format="json")


#             st.markdown("## YouTube Videos Extracted")
#             # Create a container for the carousel
#             carousel_container = st.container()

#             # Calculate number of videos per row (adjust as needed)
#             videos_per_row = 3

#             with carousel_container:
#                 # Calculate number of rows needed
#                 num_videos = len(channel_scrapped_output[0])
#                 num_rows = (num_videos + videos_per_row - 1) // videos_per_row
                
#                 for row in range(num_rows):
#                     # Create columns for each row
#                     cols = st.columns(videos_per_row)
                    
#                     # Fill each column with a video
#                     for col_idx in range(videos_per_row):
#                         video_idx = row * videos_per_row + col_idx
                        
#                         # Check if we still have videos to display
#                         if video_idx < num_videos:
#                             with cols[col_idx]:
#                                 st.video(channel_scrapped_output[0][video_idx]['url'])

#             status_container.info("Processing transcripts...")
#             st.session_state.all_files = []
#             # Calculate transcripts
#             for i in tqdm(range(len(channel_scrapped_output[0]))):


#                 # save transcript to file
#                 youtube_video_id = channel_scrapped_output[0][i]['shortcode']
                
#                 file = "transcripts/" + youtube_video_id + ".txt"
#                 st.session_state.all_files.append(file)

#                 with open(file, "w") as f:
#                     for j in range(len(channel_scrapped_output[0][i]['formatted_transcript'])):
#                         text = channel_scrapped_output[0][i]['formatted_transcript'][j]['text']
#                         start_time = channel_scrapped_output[0][i]['formatted_transcript'][j]['start_time']
#                         end_time = channel_scrapped_output[0][i]['formatted_transcript'][j]['end_time']
#                         f.write(f"({start_time:.2f}-{end_time:.2f}): {text}\n")

#                     f.close()

#             st.session_state.channel_scrapped_output = channel_scrapped_output
#             status_container.success("Scraping complete! We shall now analyze the videos and report trends...")

#         else:
#             status_container.error(f"Scraping failed with status: {status}")

#     if status['status'] == "ready":

#         status_container = st.empty()
#         with st.spinner('The agent is analyzing the videos... This may take a moment.'):
#             # create crew
#             st.session_state.crew = create_agents_and_tasks()
#             st.session_state.response = st.session_state.crew.kickoff(inputs={"file_paths": ", ".join(st.session_state.all_files)})
                    


# # ===========================
# #   Sidebar
# # ===========================
# with st.sidebar:
#     st.header("Product Analyst")
    
#     # Initialize the channels list in session state if it doesn't exist
#     if "competitors" not in st.session_state:
#         st.session_state.competitors = [""]  # Start with one empty field
    
#     # Function to add new channel field
#     def add_channel_field():
#         st.session_state.competitors.append("")
    
#     # Create input fields for each channel
#     for i, channel in enumerate(st.session_state.competitors):
#         col1, col2 = st.columns([6, 1])
#         with col1:
#             st.session_state.competitors[i] = st.text_input(
#                 "Competitor URL",
#                 value=channel,
#                 key=f"competitor_{i}",
#                 label_visibility="collapsed"
#             )
#         # Show remove button for all except the first field
#         with col2:
#             if i > 0:
#                 if st.button("❌", key=f"remove_{i}"):
#                     st.session_state.competitors.pop(i)
#                     st.rerun()
    
#     # Add channel button
#     st.button("Add Channel ➕", on_click=add_channel_field)
    
#     st.divider()
    
#     st.subheader("Date Range")
#     col1, col2 = st.columns(2)
#     with col1:
#         start_date = st.date_input("Start Date")
#         st.session_state.start_date = start_date
#         # store date as string
#         st.session_state.start_date = start_date.strftime("%Y-%m-%d")
#     with col2:
#         end_date = st.date_input("End Date")
#         st.session_state.end_date = end_date
#         st.session_state.end_date = end_date.strftime("%Y-%m-%d")

#     st.divider()
#     st.button("Start Analysis 🚀", type="primary", on_click=start_analysis)
#     # st.button("Clear Chat", on_click=reset_chat)

# # ===========================
# #   Main Chat Interface
# # ===========================

# # Main content area
# if st.session_state.response:
#     with st.spinner('Generating content... This may take a moment.'):
#         try:
#             result = st.session_state.response
#             st.markdown("### Generated Analysis")
#             st.markdown(result)
            
#             # Add download button
#             st.download_button(
#                 label="Download Content",
#                 data=result.raw,
#                 file_name=f"youtube_trend_analysis.md",
#                 mime="text/markdown"
#             )
#         except Exception as e:
#             st.error(f"An error occurred: {str(e)}")

# # Footer
# st.markdown("---")
# st.markdown("Built with CrewAI, Bright Data and Streamlit")

