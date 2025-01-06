import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import json
from tabulate import tabulate
from datetime import datetime
import os

# 상수 설정 (URL, 파일 경로 등)
TARGET_URL = 'https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)'
REGION_MAPPING_FILE = 'data/country_region_table.json'
RAW_DATA_FILE = 'results/Countries_by_GDP.json'
PROCESSED_DATA_FILE = 'results/Countries_by_GDP_Processed.json'
LOG_FILE = 'log/etl_project_log.txt'

# 로그 기록 함수
def log_message(message):
    """
    etl_project_log.txt 파일에 로그 메시지를 기록하는 함수.
    실행 시간을 포함하여 "time, log" 형식으로 기록.
    """
    with open(LOG_FILE, 'a') as f:
        current_time = datetime.now().strftime('%Y-%B-%d-%H-%M-%S')
        f.write(f"{current_time}, {message}\n")

# 실행 구분선 추가 함수
def log_separator():
    """
    로그 파일에 실행 구분선을 추가하는 함수.
    새로운 실행이 시작될 때마다 실행 시간을 명확하게 구분해줌.
    """
    with open(LOG_FILE, 'a') as f:
        f.write("\n" + "="*50 + "\n")
        current_time = datetime.now().strftime('%Y-%B-%d-%H-%M-%S')
        f.write(f"🚀 New Execution at {current_time}\n")
        f.write("="*50 + "\n\n")

# 로그 데코레이터 (함수 시작/종료 시 자동으로 로그 기록)
def log_decorator(func):
    """
    함수의 실행 시작과 완료를 자동으로 로그에 기록하는 데코레이터.
    각 함수가 시작될 때 '시작', 완료될 때 '완료'로 표시하며, 결과가 숫자인 경우 결과 값도 기록.
    """
    def wrapper(*args, **kwargs):
        log_message(f"{func.__name__} 시작")
        result = func(*args, **kwargs)
        log_message(f"{func.__name__} 완료: {result if isinstance(result, int) else 'Success'}")
        return result
    return wrapper

# GDP ETL (추출, 변환, 적재) 클래스
class GDP_ETL:
    """
    GDP 데이터를 추출, 변환, 적재하는 ETL 파이프라인 클래스.
    ETL 프로세스의 각 단계를 함수로 나누어 관리하며, 웹에서 데이터를 가져와 가공 후 저장.
    """

    def __init__(self, url):
        self.url = url
        self.soup = self._fetch_data()  # 웹 페이지에서 HTML 데이터 파싱

    def _fetch_data(self):
        """
        웹 페이지에서 HTML을 요청하여 BeautifulSoup 객체로 반환.
        요청 상태에 따라 성공 또는 실패 메시지를 로그에 기록.
        """
        response = requests.get(self.url)
        if response.status_code == 200:
            log_message("웹 페이지 요청 성공")
        else:
            log_message(f"웹 페이지 요청 실패 - 상태 코드 {response.status_code}")
        return BeautifulSoup(response.content, 'html.parser')

    @log_decorator
    def extract(self):
        """
        HTML에서 GDP 테이블을 추출하고 데이터프레임으로 변환.
        - 'wikitable' 클래스를 가진 테이블에서 GDP 데이터를 수집.
        - 테이블의 각 행(<tr>)에서 <td> 항목을 추출.
        - 추출한 데이터를 JSON 파일로 저장.
        """
        table = self.soup.find('table', {'class': 'wikitable'})
        data = []
        rows = table.find_all('tr')
        
        # 테이블의 각 행에서 국가, GDP, 연도 정보 추출
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 3:
                country = cols[0].get_text(strip=True)
                forecast = cols[1].get_text(strip=True)
                year = re.sub(r'\[.*?\]', '', cols[2].get_text(strip=True))  # 연도에서 주석 제거
                data.append([country, forecast, year])
        
        row_count = len(data)
        log_message(f"총 {row_count}개 행 추출됨")  # 총 추출된 데이터 수 로그

        # Raw 데이터를 JSON 파일로 저장
        df = pd.DataFrame(data, columns=['Country', 'GDP_USD_billion', 'Year'])
        df.to_json(RAW_DATA_FILE, orient='records', indent=4)
        file_size = os.path.getsize(RAW_DATA_FILE) / 1024  # KB 단위로 파일 크기 계산
        log_message(f"파일 저장 완료: {RAW_DATA_FILE} ({file_size:.2f} KB)")
        return df

    @log_decorator
    def transform(self, df):
        """
        데이터프레임을 변환하여 필요한 데이터만 유지하고 GDP 데이터를 가공.
        - 'World' 데이터를 제거.
        - '—' 기호를 가진 데이터(누락된 값) 필터링.
        - 쉼표(,) 제거 후 GDP 데이터를 숫자로 변환.
        - 지역 매핑 파일을 이용해 국가별로 지역 추가.
        """
        original_count = len(df)
        df = df[df['Country'] != 'World']  # World 데이터 제거
        df = df[df['GDP_USD_billion'] != '—']  # GDP 정보가 없는 경우 제거
        filtered_count = len(df)

        # GDP 데이터 변환 (쉼표 제거 후 숫자로 변환)
        df['GDP_USD_billion'] = df['GDP_USD_billion'].str.replace(',', '').astype(int)
        df['GDP_USD_billion'] = (df['GDP_USD_billion'] / 1000).round(2)  # 단위 조정 (억 달러 -> 조 달러)

        # 국가별 지역 매핑 (JSON 파일에서 지역 정보 로드)
        with open(REGION_MAPPING_FILE, 'r') as f:
            region_mapping = json.load(f)
        df['Region'] = df['Country'].map(region_mapping)

        log_message(f"필터링 완료: {original_count - filtered_count}개 행 제거됨 (총 {filtered_count}개 남음)")
        unmapped = df['Region'].isna().sum()
        log_message(f"지역 매핑 완료: {unmapped}개 국가가 매핑되지 않음")  # 매핑되지 않은 국가 수 기록
        return df

    @log_decorator
    def load(self, df):
        """
        변환된 데이터를 JSON 파일로 저장.
        저장 후 파일 크기를 로그에 기록.
        """
        df.to_json(PROCESSED_DATA_FILE, orient='records', indent=4)
        file_size = os.path.getsize(PROCESSED_DATA_FILE) / 1024  # KB 단위로 파일 크기 계산
        log_message(f"파일 저장 완료: {PROCESSED_DATA_FILE} ({file_size:.2f} KB)")
        return len(df)

    @log_decorator
    def print_gdp_over_100b(self, df):
        """
        GDP가 100B USD 이상인 국가를 출력.
        """
        gdp_over_100b = df[df['GDP_USD_billion'] >= 100]
        gdp_over_100b.index = range(1, len(gdp_over_100b) + 1)
        print("\n🌍 GDP 100B USD 이상 국가 목록:")
        print(tabulate(gdp_over_100b, headers='keys', tablefmt='grid'))
        log_message(f"GDP 100B 이상 국가 {len(gdp_over_100b)}개 출력됨")
        return len(gdp_over_100b)

    @log_decorator
    def print_region_avg_gdp(self, df):
        """
        지역별 상위 5개 국가의 GDP 평균을 계산하여 출력.
        """
        top_5_per_region = (
            df.groupby('Region')
            .apply(lambda x: x.nlargest(5, 'GDP_USD_billion'))
            .reset_index(drop=True)
        )
        region_avg_gdp = (
            top_5_per_region.groupby('Region')['GDP_USD_billion']
            .mean()
            .round(2)
            .reset_index()
            .rename(columns={'GDP_USD_billion': 'Top 5 Avg GDP'})
            .sort_values('Top 5 Avg GDP', ascending=False)
        )
        region_avg_gdp.index = range(1, len(region_avg_gdp) + 1)
        print("\n📊 Region별 상위 5개 국가의 GDP 평균:")
        print(tabulate(region_avg_gdp, headers='keys', tablefmt='grid'))
        log_message(f"Region별 GDP 평균 계산 완료 (총 {len(region_avg_gdp)}개 지역)")
        return len(region_avg_gdp)


def main():
    log_separator()
    etl = GDP_ETL(TARGET_URL)
    raw_df = etl.extract()
    transformed_df = etl.transform(raw_df)
    etl.load(transformed_df)
    etl.print_gdp_over_100b(transformed_df)
    etl.print_region_avg_gdp(transformed_df)


if __name__ == '__main__':
    main()