// import React from "react";
import { useState, useEffect } from "react";
import axios from "axios";

function App() {
    const [data, setData] = useState([]);
    const [pageCount, setPage] = useState(1);

    const get_data = async () => {
        const response = await axios.get(

            `https://picsum.photos/v2/list?page=${pageCount}&limit=12`,
        );
        console.log("Getting data from API", `https://picsum.photos/v2/list?page=${pageCount}&limit=10`);
        setData(response.data);
    };

    useEffect(function () {
        get_data()
    }, [pageCount]);



    let printUserData: any = [];

    if (data.length > 0) {
        printUserData = data.map((elem, idx) => {
            return (<>
                <div key={idx}
                    className="p-4 flex justify-center items-center rounded shadow-lg hover:scale-110 transition-transform duration-300 ease-in-out hover:text-green-400">
                    <div className="flex-col justify-center items-center ">

                        <img className="h-100 w-100 object-cover rounded " src={elem.download_url} alt="" />
                        <h2 className=" text-center m-2">{
                            elem.author
                        }</h2>
                    </div>
                </div>
            </>
            );
        });
    }

    return (<>
        <div className="  h-screen w-full ">
            <div className="">
                <div className=" grid grid-cols-4 gap-2 m-4">
                    {printUserData}
                </div>
            </div>
            {/* <button
                className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded c"
                onClick={get_data}
            >
                Click Me
            </button> */}

        </div>
        <footer className="flex justify-center  fixed bottom-0 w-full">
            <button className={`p-2 bg-pink-500 m-4 ${pageCount === 1 ? 'hidden cursor-not-allowed' : ''} hover:bg-pink-700 hover:scale-110`}
                onClick={() => {
                    if (pageCount > 1) {
                        setPage(pageCount - 1);
                    }
                    setData([])
                }}>Previous</button>
            <div className="flex justify-center m-4 p-2 ">
                {pageCount}
            </div>
            <button className="p-2 bg-red-500 m-4 hover:bg-red-700 hover:scale-110"
                onClick={() => {
                    setData([])
                    setPage(pageCount + 1);
                }}>Forward</button>
        </footer>

    </>
    );
}

export default App;

